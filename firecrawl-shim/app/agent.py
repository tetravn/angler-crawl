"""P6 — /agent browser agent tự lái (research-grade). LLM lặp observe→think→act qua crawl4ai session.

Index-grounding: observation là danh sách phần tử tương tác đánh số (build bằng _JS_SNAPSHOT,
gắn data-ai-idx, trả qua js_execution_result); action tham chiếu INDEX (không đoán selector).
Có loop/stuck detection, done-verification, page-diff, fail-closed. Xem spec P6 v2.
"""
import asyncio
import hashlib
import json
import logging
import secrets

from . import applog, clients, crawl_jobs, egress as egress_mod, transform
from .config import (
    LLM_MODEL_SMART,
    LLM_HTTP_TIMEOUT,
    AGENT_MAX_STEPS,
    AGENT_PAGE_CHARS,
    AGENT_MAX_ELEMENTS,
    AGENT_STUCK_LIMIT,
)

log = logging.getLogger("shim.agent")

_ACTIONS = {"click", "type", "scroll", "wait", "done"}

# JS injected mỗi bước: duyệt DOM lấy phần tử tương tác HIỂN THỊ, gắn data-ai-idx, trả list.
# crawl4ai serialize giá trị trả về vào js_execution_result.results[k].
_JS_SNAPSHOT = (
    "(() => {"
    " const SEL = 'a,button,input,select,textarea,[role=button],[role=link],[role=tab],"
    "[onclick],[contenteditable=true]';"
    " const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);"
    " return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };"
    " const els = [...document.querySelectorAll(SEL)].filter(vis);"
    " els.forEach((el, i) => el.setAttribute('data-ai-idx', i));"
    " return els.map((el, i) => ({ idx: i, tag: el.tagName.toLowerCase(),"
    " role: el.getAttribute('role') || el.type || null,"
    " text: (el.innerText || el.value || el.getAttribute('aria-label') || el.placeholder || '')"
    ".trim().slice(0, 120),"
    " href: el.getAttribute('href') || null,"
    " value: (el.value || '').slice(0, 60) || null }));"
    "})();"
)


def _js_click_index(i: int) -> str:
    return f'document.querySelector(\'[data-ai-idx="{int(i)}"]\')?.click();'


def _js_type_index(i: int, value: str) -> str:
    return (f'(() => {{ const el = document.querySelector(\'[data-ai-idx="{int(i)}"]\'); '
            f'if (el) {{ el.value = {json.dumps(value)}; '
            "el.dispatchEvent(new Event('input', {bubbles:true})); "
            "el.dispatchEvent(new Event('change', {bubbles:true})); } })();")


def _js_scroll() -> str:
    return "window.scrollBy(0, window.innerHeight * 2);"


def _action_to_js(action: dict) -> list[str] | None:
    """Map action (index-based) → list js_code, hoặc None nếu không cần js / thiếu index."""
    a = action.get("action")
    if a == "click":
        if action.get("index") is not None:
            return [_js_click_index(action["index"])]
        return None
    if a == "type":
        if action.get("index") is not None:
            return [_js_type_index(action["index"], action.get("value") or "")]
        return None
    if a == "scroll":
        return [_js_scroll()]
    return None


def _parse_elements(result: dict) -> list[dict]:
    """Lấy danh sách phần tử từ js_execution_result (entry list đầu tiên trong results)."""
    jer = result.get("js_execution_result") if isinstance(result, dict) else None
    if not isinstance(jer, dict) or not jer.get("success"):
        return []
    for entry in (jer.get("results") or []):
        if isinstance(entry, list):
            return [e for e in entry if isinstance(e, dict) and "idx" in e]
    return []


def _render_observation(elements: list[dict], page_md: str, new_idx: set) -> str:
    lines = ["INTERACTIVE ELEMENTS:"]
    shown = elements[:AGENT_MAX_ELEMENTS]
    for el in shown:
        idx = el.get("idx")
        mark = "*" if idx in new_idx else " "
        parts = [f"{mark}[{idx}]", str(el.get("tag") or "?")]
        if el.get("role"):
            parts.append(str(el["role"]))
        text = (el.get("text") or "").replace("\n", " ")
        if text:
            parts.append(f'"{text}"')
        if el.get("href"):
            parts.append(f"-> {el['href']}")
        if el.get("value"):
            parts.append(f"(value={el['value']})")
        lines.append(" ".join(parts))
    extra = len(elements) - len(shown)
    if extra > 0:
        lines.append(f"(+{extra} phần tử nữa — scroll để xem)")
    lines.append("")
    lines.append("PAGE TEXT:")
    lines.append((page_md or "")[:AGENT_PAGE_CHARS])
    return "\n".join(lines)


def _obs_signature(observation: str) -> str:
    return hashlib.md5((observation or "").encode("utf-8")).hexdigest()


def _page_changed(prev_sig: str | None, cur_sig: str | None) -> bool:
    return prev_sig != cur_sig


def _diff_new(prev: list[dict], cur: list[dict]) -> set:
    seen = {(e.get("tag"), e.get("text")) for e in prev}
    return {e.get("idx") for e in cur if (e.get("tag"), e.get("text")) not in seen}


def _is_stuck(step_log: list[dict], limit: int) -> bool:
    if len(step_log) < limit:
        return False

    def sig(s):
        return (s.get("action"), s.get("index"), s.get("obs_sig"))

    recent = step_log[-limit:]
    if len({sig(s) for s in recent}) == 1:                 # limit bước giống hệt
        return True
    if len(step_log) >= 4:                                  # dao động chu kỳ 2 (A,B,A,B)
        w = [sig(s) for s in step_log[-4:]]
        if w[0] == w[2] and w[1] == w[3] and w[0] != w[1]:
            return True
    if all(s.get("changed") is False for s in recent):      # limit lần liên tiếp trang không đổi
        return True
    return False


async def _llm_available() -> bool:
    return await clients.llm_available()


def _history_brief(history: list[dict]) -> str:
    out = []
    for h in history[-6:]:
        out.append(f"- {h.get('action')}: {h.get('eval') or ''} (next: {h.get('next_goal') or ''})")
    return "\n".join(out) or "(none)"


async def plan_action(prompt: str, observation: str, history: list[dict]) -> tuple[dict, str | None]:
    """LLM chọn 1 action kế (reasoning-first, theo INDEX). Fail-open → done + warning."""
    sys = ("You are a browser agent. You see a numbered list of interactive elements and the page "
           "text. Choose ONE next action, referring to elements by their [index]. "
           "Think first, then act. Return ONLY a JSON object.")
    user = (f"GOAL: {prompt}\n\nHISTORY:\n{_history_brief(history)}\n\nOBSERVATION:\n{observation}\n\n"
            'Return JSON (reasoning fields FIRST): {"thought": "...", "memory": "...", '
            '"next_goal": "...", "action": "click|type|scroll|wait|done", "index": <element index>, '
            '"value": "<text to type or ms to wait>", "answer": "<final result if done>"}. '
            'Use "done" only when the goal is achieved; put the result in "answer".')
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_SMART, timeout=LLM_HTTP_TIMEOUT)
        if data.get("action") not in _ACTIONS:
            data["action"] = "done"
        return data, None
    except Exception as exc:
        return {"action": "done", "thought": "(parse lỗi)"}, f"plan_action: {exc}"


async def verify_done(prompt: str, page_text: str) -> tuple[bool, str]:
    """Hậu kiểm: mục tiêu đã đạt CHƯA dựa trên nội dung trang. Fail-closed: lỗi → (False, ...)."""
    sys = ("You verify whether a browser agent has achieved the goal, based ONLY on the page content. "
           "Be strict; default to not-verified if unclear. Return ONLY a JSON object.")
    user = (f"GOAL: {prompt}\n\nFINAL PAGE TEXT:\n{(page_text or '')[:AGENT_PAGE_CHARS]}\n\n"
            'Return JSON: {"verified": true|false, "reason": "..."}')
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_SMART, timeout=LLM_HTTP_TIMEOUT)
        return bool(data.get("verified")), str(data.get("reason") or "")
    except Exception as exc:
        return False, f"verify lỗi: {exc}"


def _md(result: dict) -> str:
    return transform.markdown_of(result, True)


async def run_agent(job_id: str, url: str, prompt: str, params: dict, emit=None) -> None:
    """Vòng lặp observe→think→act (index-grounding, stuck-detect, done-verify, fail-closed)."""
    job = crawl_jobs.JOBS[job_id]
    warnings: list[str] = []
    steps: list[dict] = []
    step_log: list[dict] = []
    history: list[dict] = []
    result = ""
    verified = False
    stop = "maxSteps"
    sid = secrets.token_hex(8)

    async def _record(step: dict) -> None:
        steps.append(step)
        if emit:
            await emit({"type": "step", **step})

    try:
        if not await _llm_available():
            raise RuntimeError("agent cần LLM (LLM_BASE_URL/LLM_MODEL)")
        proxy = await egress_mod.resolve_proxy(params.get("egress"))
        max_steps = params.get("maxSteps") or AGENT_MAX_STEPS
        res = await clients.browser_step(url, session_id=sid, js_code=[_JS_SNAPSHOT],
                                         js_only=False, proxy=proxy)
        prev_elements = _parse_elements(res)
        obs = _render_observation(prev_elements, _md(res), set())
        page_text = _md(res)   # text trang sạch (KHÔNG lẫn marker nội bộ append vào obs)
        cur_sig = _obs_signature(obs)
        for i in range(max_steps):
            if job["status"] == "cancelled":
                return
            action, w = await plan_action(prompt, obs, history)
            if w:
                warnings.append(w)
            a = action.get("action")
            applog.event("agent", "bước hành động", request_id=job_id, step=i + 1, action=a,
                         index=action.get("index"))
            history.append({"eval": action.get("thought"), "memory": action.get("memory"),
                            "next_goal": action.get("next_goal"), "action": a})
            if a == "done":
                cand = (action.get("answer") or "").strip() or page_text
                verified, reason = await verify_done(prompt, page_text)
                applog.event("agent", "done-verify", request_id=job_id, verified=verified, reason=reason)
                await _record({"action": "done", "ok": True, "verified": verified})
                if verified or i == max_steps - 1:
                    result = cand
                    # stopReason="done" CHỈ khi đã verify; done-ở-bước-cuối-chưa-verify =
                    # hết bước (fail-closed: không gắn nhãn "done" cho kết quả chưa kiểm).
                    stop = "done" if verified else "maxSteps"
                    break
                warnings.append(f"done chưa verify: {reason} — tiếp tục")
                obs += f"\n[done bị từ chối: {reason}]"
                step_log.append({"action": "done", "index": None, "obs_sig": cur_sig, "changed": False})
                if _is_stuck(step_log, AGENT_STUCK_LIMIT):
                    stop = "stuck"
                    warnings.append("dừng: phát hiện lặp/kẹt")
                    break
                continue
            if a == "wait":
                try:
                    ms = int(action.get("value") or 1000)
                except Exception:
                    ms = 1000
                await asyncio.sleep(min(max(ms, 0), 5000) / 1000)
                await _record({"action": "wait", "ok": True})
                step_log.append({"action": "wait", "index": None, "obs_sig": cur_sig, "changed": False})
                if _is_stuck(step_log, AGENT_STUCK_LIMIT):
                    stop = "stuck"
                    warnings.append("dừng: phát hiện lặp/kẹt")
                    break
                continue
            js = _action_to_js(action)
            if not js:
                await _record({"action": a or "unknown", "ok": False})
                obs += "\n[lỗi: action/index không hợp lệ]"
                step_log.append({"action": a, "index": action.get("index"),
                                 "obs_sig": cur_sig, "changed": False})
                if _is_stuck(step_log, AGENT_STUCK_LIMIT):
                    stop = "stuck"
                    warnings.append("dừng: phát hiện lặp/kẹt")
                    break
                continue
            prev_sig = cur_sig
            try:
                res = await clients.browser_step(url, session_id=sid, js_code=js + [_JS_SNAPSHOT],
                                                 js_only=True, proxy=proxy)
                elements = _parse_elements(res)
                new_idx = _diff_new(prev_elements, elements)
                prev_elements = elements
                obs = _render_observation(elements, _md(res), new_idx)
                page_text = _md(res)
                cur_sig = _obs_signature(obs)
                changed = _page_changed(prev_sig, cur_sig)
                if not changed:
                    obs += "\n[trang không đổi sau action]"
                await _record({"action": a, "index": action.get("index"),
                               "ok": True, "changed": changed})
            except Exception as exc:
                await _record({"action": a, "index": action.get("index"), "ok": False})
                obs += f"\n[lỗi action: {exc}]"
                warnings.append(f"action {a} lỗi: {exc}")
                changed = True
            step_log.append({"action": a, "index": action.get("index"),
                             "obs_sig": cur_sig, "changed": changed})
            if _is_stuck(step_log, AGENT_STUCK_LIMIT):
                stop = "stuck"
                warnings.append("dừng: phát hiện lặp/kẹt")
                break
        if not result:
            result = page_text
        job["data"] = {"url": url, "prompt": prompt, "result": result, "verified": verified,
                       "stopReason": stop, "steps": steps, "iterations": len(steps),
                       "warnings": warnings}
        job["total"] = job["completed"] = len(steps)
        if stop == "stuck":
            applog.event("agent", "loop-detect kẹt", level=logging.WARNING, request_id=job_id,
                         steps=len(steps))
        applog.event("agent", "job xong", request_id=job_id, verified=verified,
                     stopReason=stop, steps=len(steps))
        if emit:
            await emit({"type": "done", "data": job["data"]})
        job["status"] = "completed"
    except Exception as exc:
        log.exception("agent job %s thất bại", job_id)
        applog.event("agent", "job thất bại", level=logging.ERROR, request_id=job_id, error=str(exc))
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        if job["status"] == "scraping":      # cancel/ngắt đột ngột → đánh dấu terminal (không kẹt 'scraping')
            job["status"] = "cancelled"
        try:
            await clients.close_session(sid)
        except BaseException as exc:
            log.debug("agent cleanup close_session lỗi (bỏ qua): %s", exc)
        try:
            await crawl_jobs._persist(job)
        except BaseException as exc:
            log.debug("agent cleanup persist lỗi (bỏ qua): %s", exc)


def create_agent_job(params: dict) -> str:
    """Tạo job + spawn run_agent (async). Trả job_id ngay (mirror /extract)."""
    job = crawl_jobs.new_job()
    job["data"] = {}
    crawl_jobs.persist_bg(job)
    applog.event("agent", "job tạo", request_id=job["id"], url=params.get("url"))
    crawl_jobs.spawn(run_agent(job["id"], params["url"], params["prompt"], params))
    return job["id"]
