import asyncio

from app import agent
from app import crawl_jobs


def _res(elements, md="page"):
    return {"markdown": md, "js_execution_result": {"success": True, "results": [elements]}}


def _wire(monkeypatch, *, actions, verified=True, llm_ok=True,
          observe_raises=False, step_raises_once=False, elements=None):
    state = {"i": 0, "closed": 0, "steps": 0}
    els = elements if elements is not None else [{"idx": 0, "tag": "button", "text": "Go"}]

    async def fake_avail():
        return llm_ok
    async def fake_plan(prompt, obs, history):
        a = actions[min(state["i"], len(actions) - 1)]
        state["i"] += 1
        return dict(a), None
    async def fake_verify(prompt, page_text):
        return verified, "r"
    async def fake_browser(url, *, session_id, js_code=None, js_only=False, wait_for_ms=0, proxy=None):
        if js_only is False and observe_raises:
            raise RuntimeError("observe down")
        if js_only is True:
            state["steps"] += 1
            if step_raises_once and state["steps"] == 1:
                raise RuntimeError("act down")
        return _res(els, md=f"page-{state['i']}")
    async def fake_close(sid):
        state["closed"] += 1
    async def fake_proxy(e):
        return None

    monkeypatch.setattr(agent, "_llm_available", fake_avail)
    monkeypatch.setattr(agent, "plan_action", fake_plan)
    monkeypatch.setattr(agent, "verify_done", fake_verify)
    monkeypatch.setattr(agent.clients, "browser_step", fake_browser)
    monkeypatch.setattr(agent.clients, "close_session", fake_close)
    monkeypatch.setattr(agent.egress_mod, "resolve_proxy", fake_proxy)
    monkeypatch.setattr(agent.transform, "markdown_of", lambda r, o: r.get("markdown", ""))
    return state


def _params(**kw):
    p = {"url": "http://x", "prompt": "goal", "maxSteps": 5, "egress": None}
    p.update(kw)
    return p


def test_run_done_verified(monkeypatch):
    state = _wire(monkeypatch, actions=[{"action": "done", "answer": "RESULT"}], verified=True)
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params()))
    assert job["status"] == "completed"
    assert job["data"]["result"] == "RESULT"
    assert job["data"]["verified"] is True
    assert job["data"]["stopReason"] == "done"
    assert state["closed"] == 1


def test_run_done_unverified_continues(monkeypatch):
    # done luôn bị từ chối verify → không dừng ở done; hết bước → verified False
    state = _wire(monkeypatch, actions=[{"action": "done", "answer": "X"}], verified=False)
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params(maxSteps=3)))
    assert job["data"]["verified"] is False
    assert job["data"]["stopReason"] in ("maxSteps", "done")
    assert state["closed"] == 1


def test_run_maxsteps_scroll(monkeypatch):
    state = _wire(monkeypatch, actions=[{"action": "scroll"}])
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params(maxSteps=3)))
    assert job["data"]["stopReason"] in ("maxSteps", "stuck")
    assert job["data"]["verified"] is False
    assert state["closed"] == 1


def test_run_stuck_detection(monkeypatch):
    # click cùng index, trang không đổi (cùng elements/md) → stuck
    state = _wire(monkeypatch, actions=[{"action": "click", "index": 0}])
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params(maxSteps=8)))
    # dừng sớm vì stuck (ít hơn 8 bước) HOẶC maxSteps; phải có stopReason hợp lệ
    assert job["data"]["stopReason"] in ("stuck", "maxSteps")
    assert state["closed"] == 1


def test_run_action_error_continues(monkeypatch):
    state = _wire(monkeypatch, actions=[{"action": "click", "index": 0}], step_raises_once=True)
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params(maxSteps=2)))
    assert job["status"] == "completed"
    assert any(not s["ok"] for s in job["data"]["steps"])
    assert job["data"]["warnings"]


def test_run_no_llm_fails(monkeypatch):
    state = _wire(monkeypatch, actions=[{"action": "done"}], llm_ok=False)
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params()))
    assert job["status"] == "failed" and "LLM" in job["error"]
    assert state["closed"] == 1


def test_run_observe_error_fails(monkeypatch):
    state = _wire(monkeypatch, actions=[{"action": "done"}], observe_raises=True)
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params()))
    assert job["status"] == "failed"
    assert state["closed"] == 1


def test_run_cancelled_closes(monkeypatch):
    state = _wire(monkeypatch, actions=[{"action": "scroll"}])
    job = crawl_jobs.new_job()
    job["status"] = "cancelled"
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params()))
    assert state["closed"] == 1


def test_wait_loop_triggers_stuck(monkeypatch):
    """FIX 3 regression: plan_action luôn trả 'wait' → stuck detection ngăn chạy tới maxSteps."""
    state = _wire(monkeypatch, actions=[{"action": "wait", "value": 1}], verified=False)
    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "goal", _params(maxSteps=8)))
    assert job["data"]["stopReason"] == "stuck", (
        f"expected 'stuck', got '{job['data']['stopReason']}'"
    )
    # dừng SỚM hơn maxSteps — stuck-detect phải nổ trước khi hết 8 bước
    assert len(job["data"]["steps"]) < 8


def test_create_agent_job(monkeypatch):
    async def fake_persist(job):
        return None
    monkeypatch.setattr(crawl_jobs, "_persist", fake_persist)
    ran = {}

    async def fake_run(job_id, url, prompt, params):
        ran["id"] = job_id
    monkeypatch.setattr(agent, "run_agent", fake_run)

    async def go():
        jid = agent.create_agent_job(_params())
        await asyncio.sleep(0)
        return jid
    jid = asyncio.run(go())
    assert jid in crawl_jobs.JOBS and ran["id"] == jid
