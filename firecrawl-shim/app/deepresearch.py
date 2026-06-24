"""Deep research native loop (P4) — mượn kiến trúc Firesearch, chạy trong shim.

Vòng lặp: bẻ câu hỏi (plan) → tìm + scrape → chấm độ-tự-tin từng câu (check) →
lặp với query thay thế (alt) → tổng hợp có trích dẫn (synthesize). Job async qua crawl_jobs.

Fail-open: plan/check/alt lỗi → fallback mềm + warning. synthesize lỗi → raise (job failed).
LLM-gated: thiếu LLM → plan/synthesize raise → job failed (như /extract).
"""
import logging
import re

from . import (applog, clients, crawl_jobs, egress as egress_mod, excerpt,
               query_intent, ranking, research as research_mod, scrape as scrape_mod)
from .config import (
    LLM_MODEL_FAST,
    LLM_MODEL_SMART,
    LLM_HTTP_TIMEOUT,
    CROSS_CHECK_CHARS,
    DR_RENDER_WAIT_MS,
    DR_MAX_RENDER,
    DR_MIN_NUMERIC,
)

log = logging.getLogger("shim.deepresearch")

MIN_CONF = 0.3      # dưới mức này = chưa trả lời
EARLY_TERM = 0.8    # mọi câu đạt mức này → dừng sớm


def _evidence_supported(evidence, corpus: str) -> bool:
    """True nếu quote bằng chứng thật sự bám vào text nguồn (chống model bịa 'answered').

    Lấy các token đáng kể của quote (gồm cả số/%); đòi ít nhất 60% xuất hiện trong corpus nguồn.
    Quote quá ngắn (< 3 token) coi như không đủ bằng chứng."""
    words = re.findall(r"[a-z0-9%]{2,}", (evidence or "").lower())
    uniq = set(words)
    if len(uniq) < 3:
        return False
    hit = sum(1 for w in uniq if w in corpus)
    return hit / len(uniq) >= 0.6


async def plan_subqueries(query: str) -> tuple[list[dict], list[str]]:
    """Bẻ `query` thành các câu hỏi factual. Fail-open → 1 câu = query gốc + warning."""
    sys = ("Break a research question into 3-6 atomic, self-contained factual sub-questions. "
           "Each sub-question must ask for ONE fact answerable on its own from a single source. "
           "Do NOT bundle multiple named entities, sources, time periods, or aspects into one "
           "sub-question: split 'approval per Gallup, Pew and YouGov' into separate questions, or "
           "ask one general 'what is the latest approval rating' question. Each question must stand "
           "alone without referring back to the original question. Return ONLY a JSON object.")
    user = (f"Question: {query}\n\n"
            'Return JSON: {"subqueries": [{"question": "...", "search_query": "..."}]} '
            '(3-6 items, each atomic and independently answerable). '
            '"search_query" is a concise web-search query for that single sub-question.')
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_SMART, timeout=LLM_HTTP_TIMEOUT)
        items = data.get("subqueries")
        subs: list[dict] = []
        for it in (items or []):
            q = (it.get("question") or "").strip()
            sq = (it.get("search_query") or q).strip()
            if q:
                subs.append({"question": q, "search_query": sq,
                             "answered": False, "confidence": 0.0, "sources": []})
        if not subs:
            raise ValueError("plan rỗng")
        return subs, []
    except Exception as exc:
        fallback = [{"question": query, "search_query": query,
                     "answered": False, "confidence": 0.0, "sources": []}]
        return fallback, [f"plan_subqueries: {exc} — dùng 1 câu hỏi = query gốc"]


async def check_answers(
    subqueries: list[dict], sources: list[dict]
) -> tuple[list[dict], list[str]]:
    """Chấm mỗi câu đã được nguồn trả lời chưa + confidence. Chỉ nâng, không hạ. Fail-open."""
    if not sources:
        return subqueries, []
    # Trích đoạn liên quan tới các câu hỏi (keyword + số liệu) thay vì N ký tự đầu (thường là nav).
    terms = excerpt.query_terms(" ".join(sq["question"] for sq in subqueries))
    blocks = []
    corpus_parts = []
    for n, s in enumerate(sources, 1):
        ex = excerpt.relevant_excerpt(s.get("markdown") or "", terms, CROSS_CHECK_CHARS)
        blocks.append(f"[{n}] {s['url']}\n{ex}")
        corpus_parts.append(ex.lower())
    corpus = " ".join(corpus_parts)
    qlist = "\n".join(f"{i}. {sq['question']}" for i, sq in enumerate(subqueries))
    # Đòi bằng chứng: model phải trích câu/cụm THẬT từ nguồn cho mỗi câu đã trả lời. Sau đó ta tự kiểm
    # quote có khớp text nguồn không, để chặn false-positive (model phán "answered" mà nguồn không hề có).
    sys = ("Decide which questions the sources answer. Use ONLY the sources. For each question you mark "
           "answered, you MUST include 'evidence': a short exact quote copied from the sources that "
           "supports it. If no source contains the answer, mark answered=false with empty evidence. "
           "Return ONLY a JSON object.")
    user = (f"QUESTIONS:\n{qlist}\n\nSOURCES:\n" + "\n\n---\n\n".join(blocks) +
            '\n\nReturn JSON: {"results": [{"index": 0, "answered": true, "confidence": 0.0, '
            '"evidence": "exact quote from a source"}]} where index is the question number above.')
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_SMART, timeout=LLM_HTTP_TIMEOUT)
        for r in (data.get("results") or []):
            i = r.get("index")
            if not (isinstance(i, int) and 0 <= i < len(subqueries)):
                continue
            c = float(r.get("confidence") or 0)
            answered = bool(r.get("answered")) and c >= MIN_CONF
            # Gate chống ảo: "answered" chỉ giữ khi quote thật sự bám vào text nguồn.
            if answered and not _evidence_supported(r.get("evidence"), corpus):
                answered = False
                c = min(c, MIN_CONF - 0.01)      # hạ dưới ngưỡng để vòng sau còn tìm tiếp
            if c > subqueries[i]["confidence"]:
                subqueries[i]["confidence"] = c
                subqueries[i]["answered"] = answered
        return subqueries, []
    except Exception as exc:
        return subqueries, [f"check_answers: {exc}"]


async def alt_queries(pending: list[dict]) -> tuple[list[str], list[str]]:
    """Sinh search query thay thế cho các câu chưa trả lời. Fail-open → search_query gốc."""
    qlist = "\n".join(f"- {sq['question']}" for sq in pending)
    sys = ("Generate alternative web-search queries to answer questions not yet answered. "
           "Return ONLY a JSON object.")
    user = (f"Unanswered questions:\n{qlist}\n\n"
            'Return JSON: {"queries": ["...", "..."]} (one or two per question).')
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_FAST, timeout=LLM_HTTP_TIMEOUT)
        qs = [q.strip() for q in (data.get("queries") or [])
              if isinstance(q, str) and q.strip()]
        if not qs:
            raise ValueError("alt rỗng")
        return qs, []
    except Exception as exc:
        return [sq["search_query"] for sq in pending], [f"alt_queries: {exc} — dùng lại query gốc"]


async def synthesize(query: str, sources: list[dict], on_token=None) -> str:
    """Tổng hợp câu trả lời markdown có trích dẫn [n]. KHÔNG fail-open (lỗi → raise → job failed).

    on_token (async) có → stream token (cho SSE) qua clients.stream_chat; None → llm_chat thường."""
    # Trích đoạn liên quan tới truy vấn cho mỗi nguồn, để answer bám đúng dữ kiện (số, ngày, tên)
    # nằm sâu trong trang thay vì phần nav/boilerplate ở đầu.
    terms = excerpt.query_terms(query)
    blocks = []
    for n, s in enumerate(sources, 1):
        ex = excerpt.relevant_excerpt(s.get("markdown") or "", terms, CROSS_CHECK_CHARS)
        blocks.append(f"[{n}] {s.get('title') or s['url']}\n{ex}")
    sys = ("Answer the question using ONLY the provided sources. Cite sources inline as [n] "
           "matching their numbers. Use markdown. Do not invent sources or facts.")
    user = f"Question: {query}\n\nSOURCES:\n" + "\n\n---\n\n".join(blocks)
    msgs = [{"role": "system", "content": sys}, {"role": "user", "content": user}]
    if on_token is not None:
        return await clients.stream_chat(msgs, model=LLM_MODEL_SMART, json_mode=False,
                                         timeout=LLM_HTTP_TIMEOUT, on_token=on_token)
    return await clients.llm_chat(msgs, model=LLM_MODEL_SMART, json_mode=False,
                                  timeout=LLM_HTTP_TIMEOUT)


def create_deep_research_job(params: dict) -> str:
    """Tạo job + spawn _run (async). Trả job_id ngay (mirror /extract)."""
    job = crawl_jobs.new_job()
    job["data"] = {}
    crawl_jobs.persist_bg(job)
    applog.event("deepresearch", "job tạo", request_id=job["id"], query=params.get("query"))
    crawl_jobs.spawn(_run(job["id"], params))
    return job["id"]


async def _run(job_id: str, params: dict, emit=None) -> None:
    """Vòng lặp deep-research. Set job['data'] + status. Fail-open từng bước; failed nếu synthesize/LLM lỗi."""
    job = crawl_jobs.JOBS[job_id]
    warnings: list[str] = []
    attempt = 0
    try:
        query = params["query"]
        proxy = await egress_mod.resolve_proxy(params.get("egress"))
        try:
            intent = await query_intent.analyze_intent(query)   # cho ranking; fail-open
        except Exception:
            intent = None
        subqueries, w = await plan_subqueries(query)
        warnings += w
        if emit:
            await emit({"type": "phase", "phase": "plan", "subQuestions": len(subqueries)})
        job["total"] = len(subqueries)
        sources: list[dict] = []
        seen: set[str] = set()
        iterations_done = 0
        # #3: nếu truy vấn cần số liệu, để dành ngân sách render JS cho trang trả về không có số.
        numeric_q = excerpt.wants_numbers(query)
        q_terms = excerpt.query_terms(query)
        rendered = 0
        for attempt in range(max(1, int(params.get("maxIterations") or 1))):
            iterations_done = attempt + 1
            applog.event("deepresearch", "vòng lặp bắt đầu", request_id=job_id, iteration=attempt + 1)
            if emit:
                await emit({"type": "iteration", "n": attempt + 1})
            if job["status"] == "cancelled":
                return
            pending = [sq for sq in subqueries if sq["confidence"] < MIN_CONF]
            if not pending:
                break
            if attempt == 0:
                queries = [sq["search_query"] for sq in pending]
            else:
                queries, w = await alt_queries(pending)
                warnings += w
            queries = queries[:params["maxQueries"]]
            # Gom kết quả mọi query trong vòng, dedupe + loại nguồn rác (social/chat/từ điển/lịch),
            # rồi xếp hạng đa tín hiệu (chất lượng + mới) trước khi scrape. Nhờ vậy scrape budget đổ
            # vào nguồn tốt nhất thay vì thứ tự thô của SearXNG, và rác không nhét vào tổng hợp.
            candidates: list[dict] = []
            cand_seen: set[str] = set()
            for q in queries:
                if job["status"] == "cancelled":
                    return
                try:
                    results = await clients.searxng_search(q, limit=params["maxSourcesPerQuery"])
                except Exception:
                    results = []
                for r in results:
                    url = r.get("url")
                    if not url or url in seen or url in cand_seen:
                        continue
                    if research_mod.is_low_value(url):
                        continue
                    cand_seen.add(url)
                    candidates.append(r)
            ranked = ranking.rank(candidates, intent, params["maxScrapePerIteration"])
            for r in ranked:
                if job["status"] == "cancelled":
                    return
                url = r["url"]
                seen.add(url)
                try:
                    data, _r, _ = await scrape_mod.scrape(url, ["markdown"], True, proxy=proxy)
                except Exception:
                    continue
                if (data.get("metadata") or {}).get("blocked"):
                    continue
                md = data.get("markdown")
                # #3: câu hỏi cần số mà đoạn liên quan nghèo số liệu (dashboard render bằng JS — đoạn
                # text chỉ có vài nhãn trục) → scrape lại một lần có chờ JS, bypass cache. Chỉ nhận bản
                # render nếu nó cho NHIỀU số hơn. Giới hạn DR_MAX_RENDER lần/job để chặn chi phí.
                if md and numeric_q and rendered < DR_MAX_RENDER:
                    n0 = excerpt.numeric_count(excerpt.relevant_excerpt(md, q_terms, CROSS_CHECK_CHARS))
                    if n0 < DR_MIN_NUMERIC:
                        try:
                            d2, _r2, _ = await scrape_mod.scrape(
                                url, ["markdown"], True, proxy=proxy,
                                wait_for_ms=DR_RENDER_WAIT_MS, bypass_cache=True)
                            md2 = d2.get("markdown")
                            if md2 and not (d2.get("metadata") or {}).get("blocked"):
                                n1 = excerpt.numeric_count(
                                    excerpt.relevant_excerpt(md2, q_terms, CROSS_CHECK_CHARS))
                                if n1 > n0:
                                    md = md2
                                    rendered += 1
                                    applog.event("deepresearch", "render JS bắt số",
                                                 request_id=job_id, url=url, before=n0, after=n1)
                        except Exception:
                            pass
                if md:
                    sources.append({"url": url, "title": r.get("title"), "markdown": md})
            subqueries, w = await check_answers(subqueries, sources)
            warnings += w
            job["completed"] = sum(1 for sq in subqueries if sq["confidence"] >= MIN_CONF)
            await crawl_jobs._persist(job)
            if all(sq["confidence"] >= EARLY_TERM for sq in subqueries):
                break
        if job["status"] == "cancelled":   # hủy ngay trước bước synthesize (dài nhất)
            return
        # #1: câu hỏi cần số → đưa nguồn giàu số liệu lên trước khi synthesize. SourceType ở deep-research
        # hầu hết là "web" (SearXNG candidate không kèm category) nên không phân biệt prose/dashboard
        # bằng nhãn được; thay vào đó xếp theo lượng số liệu thực có trong text. Ổn định, không bỏ nguồn.
        if numeric_q and len(sources) > 1:
            sources.sort(
                key=lambda s: excerpt.numeric_count(
                    excerpt.relevant_excerpt(s.get("markdown") or "", q_terms, CROSS_CHECK_CHARS)),
                reverse=True)
        if emit:
            await emit({"type": "phase", "phase": "synthesize"})

            async def _tok(t):
                await emit({"type": "token", "text": t})

            answer = await synthesize(query, sources, on_token=_tok)
        else:
            answer = await synthesize(query, sources)
        job["data"] = {
            "query": query,
            "answer": answer,
            "sources": [{"n": i + 1, "url": s["url"], "title": s["title"]}
                        for i, s in enumerate(sources)],
            "subQuestions": [{"question": sq["question"], "answered": sq["answered"],
                              "confidence": sq["confidence"]} for sq in subqueries],
            "iterations": iterations_done,
            "warnings": warnings,
        }
        job["completed"] = job["total"]
        job["status"] = "completed"
        applog.event("deepresearch", "job xong", request_id=job_id,
                     sources=len(sources), iterations=iterations_done)
        if emit:
            await emit({"type": "done", "data": job["data"]})
        await crawl_jobs._persist(job)
    except Exception as exc:
        log.exception("deep-research job %s thất bại", job_id)
        applog.event("deepresearch", "job thất bại", level=logging.ERROR,
                     request_id=job_id, error=str(exc))
        job["status"] = "failed"
        job["error"] = str(exc)
        await crawl_jobs._persist(job)
    finally:
        if job["status"] == "scraping":      # cancel/ngắt đột ngột → terminal
            job["status"] = "cancelled"
            try:
                await crawl_jobs._persist(job)
            except BaseException as exc:
                log.debug("deep-research cleanup persist lỗi (bỏ qua): %s", exc)
