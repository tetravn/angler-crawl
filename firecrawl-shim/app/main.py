"""Firecrawl-compatible API → Crawl4AI (+ FlareSolverr cho Cloudflare).

Mặt ngoài nói "tiếng Firecrawl" để agent chỉ-biết-Firecrawl dùng được mà không
sửa code: trỏ FIRECRAWL_API_URL về gateway là chạy.

Hỗ trợ cả tiền tố /v1 và /v2 (schema giống nhau).
"""
import asyncio
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import (
    agent,
    applog,
    clients,
    crawl_jobs,
    deepresearch,
    egress as egress_mod,
    extract as extract_mod,
    monitor,
    query_intent,
    research as research_mod,
    research_llm,
    scrape as scrape_mod,
    search as search_mod,
    sse,
    store,
    transcript as transcript_mod,
)
from .config import CRAWL_CONCURRENCY, LOG_TTL_SECONDS
from .models import (
    AgentRequest,
    BatchScrapeRequest,
    CrawlRequest,
    DeepResearchRequest,
    ExtractRequest,
    MapRequest,
    MonitorRequest,
    ResearchRequest,
    ScrapeRequest,
    SearchRequest,
    TranscriptRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("shim")

app = FastAPI(title="firecrawl-shim", version="1.0.0")


@app.middleware("http")
async def _request_id_mw(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    applog.set_request_id(rid)
    start = asyncio.get_running_loop().time()
    response = await call_next(request)
    ms = int((asyncio.get_running_loop().time() - start) * 1000)
    applog.event("http", f"{request.method} {request.url.path}",
                 status=response.status_code, ms=ms,
                 path=request.url.path, method=request.method)
    response.headers["X-Request-Id"] = rid
    return response


@app.on_event("startup")
async def _startup() -> None:
    store.init_db()
    await store.purge_expired()
    await store.purge_events(LOG_TTL_SECONDS, time.time())
    # Nạp lại các job chưa hết hạn vào RAM (job đang dở coi như interrupted).
    for job in await store.load_all():
        if job.get("status") == "scraping":
            job["status"] = "failed"
            job["error"] = "interrupted by restart"
        crawl_jobs.JOBS[job["id"]] = job
    log.info("nạp lại %d job từ SQLite", len(crawl_jobs.JOBS))
    await applog.start_writer()
    await monitor.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await applog.stop_writer()
    await clients.aclose()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {
        "service": "firecrawl-shim",
        "backend": "crawl4ai + flaresolverr + searxng",
        "endpoints": [
            "POST /v1/scrape",
            "POST /v1/search",
            "POST /v1/research",
            "POST /v1/map",
            "POST /v1/crawl",
            "GET /v1/crawl/{id}",
            "DELETE /v1/crawl/{id}",
            "GET /v1/crawl/{id}/errors",
            "POST /v1/batch/scrape",
            "GET /v1/batch/scrape/{id}",
            "POST /v1/extract",
            "GET /v1/extract/{id}",
            "POST /v1/deep-research",
            "POST /v1/deep-research/stream",
            "POST /v1/agent",
            "POST /v1/agent/stream",
            "POST /v1/transcript",
            "POST /v1/monitor",
            "GET /v1/logs",
            "GET /v1/stats",
        ],
    }


def _err(message: str, status: int = 500) -> JSONResponse:
    return JSONResponse(status_code=status, content={"success": False, "error": message})


# ─── /scrape ────────────────────────────────────────────────────────────
async def _scrape(body: ScrapeRequest) -> JSONResponse | dict:
    try:
        proxy = await egress_mod.resolve_proxy(body.egress)
        data, _result, used_fs = await scrape_mod.scrape(
            body.url,
            body.formats,
            body.onlyMainContent,
            body.waitFor,
            body.timeout,
            body.headers,
            proxy=proxy,
            fallback=body.fallback,
        )
    except Exception as exc:
        log.exception("scrape lỗi")
        applog.event("scrape", "scrape lỗi", level=logging.ERROR, url=body.url, error=str(exc))
        return _err(f"scrape failed: {exc}")
    if used_fs:
        log.info("scrape %s qua FlareSolverr (Cloudflare bypass)", body.url)
    return {"success": True, "data": data}


@app.post("/v1/scrape")
@app.post("/v2/scrape")
async def scrape_endpoint(body: ScrapeRequest):
    return await _scrape(body)


# ─── /map ───────────────────────────────────────────────────────────────
async def _map(body: MapRequest) -> JSONResponse | dict:
    try:
        links = await scrape_mod.site_map(
            body.url, body.limit, body.includeSubdomains, body.search
        )
    except Exception as exc:
        log.exception("map lỗi")
        applog.event("scrape", "map lỗi", level=logging.ERROR, url=body.url, error=str(exc))
        return _err(f"map failed: {exc}")
    return {"success": True, "links": links}


@app.post("/v1/map")
@app.post("/v2/map")
async def map_endpoint(body: MapRequest):
    return await _map(body)


# ─── /crawl (async) ─────────────────────────────────────────────────────
def _status_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    prefix = request.headers.get("x-forwarded-prefix", "")
    return f"{proto}://{host}{prefix}"


async def _crawl(body: CrawlRequest, request: Request) -> JSONResponse | dict:
    try:
        proxy = await egress_mod.resolve_proxy(body.egress)
        req = body.model_dump()
        req["_proxy"] = proxy
        job_id = crawl_jobs.create_job(req)
    except Exception as exc:
        log.exception("crawl khởi tạo lỗi")
        applog.event("crawl", "crawl khởi tạo lỗi", level=logging.ERROR,
                     url=body.url, error=str(exc))
        return _err(f"crawl failed: {exc}")
    return _accepted(request, "crawl", job_id)


@app.post("/v1/crawl")
@app.post("/v2/crawl")
async def crawl_endpoint(body: CrawlRequest, request: Request):
    return await _crawl(body, request)


def _job_body(job: dict) -> dict:
    return {
        "success": job["status"] != "failed",
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "creditsUsed": job["creditsUsed"],
        "expiresAt": job["expiresAt"],
        "data": job["data"],
        "error": job["error"],
    }


def _accepted(request: Request, prefix: str, job_id: str) -> dict:
    """Response chuẩn cho endpoint tạo job async (id + URL poll)."""
    return {"success": True, "id": job_id, "url": f"{_status_base(request)}/v1/{prefix}/{job_id}"}


def _job_status(job_id: str) -> JSONResponse | dict:
    job = crawl_jobs.JOBS.get(job_id)
    return _job_body(job) if job else _err("job not found", status=404)


def _job_cancel(job_id: str) -> JSONResponse | dict:
    if job_id not in crawl_jobs.JOBS:
        return _err("job not found", status=404)
    crawl_jobs.cancel_job(job_id)
    return {"success": True, "status": "cancelled"}


@app.get("/v1/crawl/{job_id}")
@app.get("/v2/crawl/{job_id}")
async def crawl_status(job_id: str):
    return _job_status(job_id)


@app.delete("/v1/crawl/{job_id}")
@app.delete("/v2/crawl/{job_id}")
async def crawl_cancel(job_id: str):
    return _job_cancel(job_id)


@app.get("/v1/crawl/{job_id}/errors")
@app.get("/v2/crawl/{job_id}/errors")
async def crawl_errors(job_id: str):
    job = crawl_jobs.JOBS.get(job_id)
    if not job:
        return _err("job not found", status=404)
    errors = [{"error": job["error"]}] if job.get("error") else []
    return {"success": True, "errors": errors, "robotsBlocked": []}


# ─── /search (qua SearXNG) ──────────────────────────────────────────────
async def _do_search(body: SearchRequest) -> list[dict]:
    proxy = await egress_mod.resolve_proxy(body.egress)
    opts = body.scrapeOptions.model_dump() if body.scrapeOptions else None
    cats = ",".join(body.categories) if body.categories else None
    return await search_mod.search(
        body.query, limit=body.limit, lang=body.lang, scrape_options=opts, proxy=proxy,
        categories=cats,
    )


@app.post("/v1/search")
async def search_v1(body: SearchRequest):
    # v1: data là LIST phẳng.
    try:
        return {"success": True, "data": await _do_search(body)}
    except Exception as exc:
        log.exception("search lỗi")
        applog.event("search", "search lỗi", level=logging.ERROR,
                     query=body.query, error=str(exc))
        return _err(f"search failed: {exc}")


@app.post("/v2/search")
async def search_v2(body: SearchRequest):
    # v2: SDK mong data là OBJECT {web,news,images}. Ta đổ kết quả vào `web`.
    try:
        return {"success": True, "data": {"web": await _do_search(body)}}
    except Exception as exc:
        log.exception("search lỗi")
        applog.event("search", "search lỗi", level=logging.ERROR,
                     query=body.query, error=str(exc))
        return _err(f"search failed: {exc}")


# ─── /batch/scrape (async) ──────────────────────────────────────────────
@app.post("/v1/batch/scrape")
@app.post("/v2/batch/scrape")
async def batch_scrape_endpoint(body: BatchScrapeRequest, request: Request):
    try:
        proxy = await egress_mod.resolve_proxy(body.egress)
        opts = {"formats": body.formats, "onlyMainContent": body.onlyMainContent}
        job_id = crawl_jobs.create_batch_job(body.urls, opts, proxy)
    except Exception as exc:
        log.exception("batch khởi tạo lỗi")
        applog.event("batch", "batch khởi tạo lỗi", level=logging.ERROR, error=str(exc))
        return _err(f"batch failed: {exc}")
    return _accepted(request, "batch/scrape", job_id)


@app.get("/v1/batch/scrape/{job_id}")
@app.get("/v2/batch/scrape/{job_id}")
async def batch_scrape_status(job_id: str):
    return _job_status(job_id)


# ─── /extract (LLM) ─────────────────────────────────────────────────────
@app.post("/v1/extract")
@app.post("/v2/extract")
async def extract_endpoint(body: ExtractRequest, request: Request):
    try:
        job_id = extract_mod.create_extract_job(body.urls, body.prompt, body.schema_)
    except Exception as exc:
        log.exception("extract khởi tạo lỗi")
        applog.event("extract", "extract khởi tạo lỗi", level=logging.ERROR, error=str(exc))
        return _err(f"extract failed: {exc}")
    return _accepted(request, "extract", job_id)


@app.get("/v1/extract/{job_id}")
@app.get("/v2/extract/{job_id}")
async def extract_status(job_id: str):
    return _job_status(job_id)


# ─── /logs + /stats (activity log — gác token ở Caddy qua ANGLER_LOG_API_KEY) ──
def _parse_window(window: str) -> float:
    """'24h'|'90m'|'3600' → giây. Mặc định 86400 nếu không hợp lệ."""
    try:
        w = window.strip().lower()
        if w.endswith("h"):
            return float(w[:-1]) * 3600
        if w.endswith("m"):
            return float(w[:-1]) * 60
        if w.endswith("d"):
            return float(w[:-1]) * 86400
        return float(w)
    except Exception:
        return 86400.0


@app.get("/v1/logs")
@app.get("/v2/logs")
async def logs_endpoint(kind: str | None = None, level: str | None = None,
                        request_id: str | None = None, since: float | None = None,
                        until: float | None = None, limit: int = 200):
    try:
        limit = max(1, min(limit, 1000))
        rows = await store.query_events(kind, level, request_id, since, until, limit)
        return {"success": True, "events": rows, "count": len(rows)}
    except Exception as exc:
        log.exception("logs lỗi")
        return _err(f"logs failed: {exc}")


@app.get("/v1/stats")
@app.get("/v2/stats")
async def stats_endpoint(window: str = "24h"):
    try:
        return {"success": True, "stats": await store.stats_events(
            _parse_window(window), time.time())}
    except Exception as exc:
        log.exception("stats lỗi")
        return _err(f"stats failed: {exc}")


# ─── /deep-research (vòng lặp LLM, async job) ───────────────────────────
@app.post("/v1/deep-research")
@app.post("/v2/deep-research")
async def deep_research_endpoint(body: DeepResearchRequest, request: Request):
    """Nghiên cứu sâu (async job, cần LLM): bẻ câu hỏi → tìm/scrape nhiều vòng → tổng hợp có trích dẫn. Trả id; poll GET .../deep-research/{id}."""
    try:
        job_id = deepresearch.create_deep_research_job(body.model_dump())
    except Exception as exc:
        log.exception("deep-research khởi tạo lỗi")
        applog.event("deepresearch", "deep-research khởi tạo lỗi", level=logging.ERROR,
                     error=str(exc))
        return _err(f"deep-research failed: {exc}")
    return _accepted(request, "deep-research", job_id)


@app.get("/v1/deep-research/{job_id}")
@app.get("/v2/deep-research/{job_id}")
async def deep_research_status(job_id: str):
    return _job_status(job_id)


@app.delete("/v1/deep-research/{job_id}")
@app.delete("/v2/deep-research/{job_id}")
async def deep_research_cancel(job_id: str):
    return _job_cancel(job_id)


@app.post("/v1/deep-research/stream")
@app.post("/v2/deep-research/stream")
async def deep_research_stream(body: DeepResearchRequest):
    job = crawl_jobs.new_job()
    job["data"] = {}
    crawl_jobs.persist_bg(job)

    async def factory(emit):
        await deepresearch._run(job["id"], body.model_dump(), emit=emit)

    return await sse.sse_response(factory)


# ─── /agent (browser agent tự lái, async job) ───────────────────────────
@app.post("/v1/agent")
@app.post("/v2/agent")
async def agent_endpoint(body: AgentRequest, request: Request):
    """Browser agent tự lái (async job, cần LLM): điều hướng trang theo mục tiêu (index-grounding + loop-detect + done-verify). Trả id; poll GET .../agent/{id}."""
    try:
        job_id = agent.create_agent_job(body.model_dump())
    except Exception as exc:
        log.exception("agent khởi tạo lỗi")
        applog.event("agent", "agent khởi tạo lỗi", level=logging.ERROR, error=str(exc))
        return _err(f"agent failed: {exc}")
    return _accepted(request, "agent", job_id)


@app.get("/v1/agent/{job_id}")
@app.get("/v2/agent/{job_id}")
async def agent_status(job_id: str):
    return _job_status(job_id)


@app.delete("/v1/agent/{job_id}")
@app.delete("/v2/agent/{job_id}")
async def agent_cancel(job_id: str):
    return _job_cancel(job_id)


@app.post("/v1/agent/stream")
@app.post("/v2/agent/stream")
async def agent_stream(body: AgentRequest):
    job = crawl_jobs.new_job()
    job["data"] = {}
    crawl_jobs.persist_bg(job)

    async def factory(emit):
        await agent.run_agent(job["id"], body.url, body.prompt, body.model_dump(), emit=emit)

    return await sse.sse_response(factory)


# ─── /transcript (video → caption) ──────────────────────────────────────
@app.post("/v1/transcript")
@app.post("/v2/transcript")
async def transcript_endpoint(body: TranscriptRequest):
    try:
        proxy = await egress_mod.resolve_proxy(body.egress)
        sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

        async def one(u: str) -> dict:
            async with sem:
                t = await transcript_mod.get_transcript(u, languages=body.languages, proxy=proxy)
                return {"url": u, **t}

        data = await asyncio.gather(*[one(u) for u in body.urls])
        return {"success": True, "data": list(data)}
    except Exception as exc:
        log.exception("transcript lỗi")
        applog.event("transcript", "transcript lỗi", level=logging.ERROR, error=str(exc))
        return _err(f"transcript failed: {exc}")


# ─── /monitor (theo dõi thay đổi trang) ─────────────────────────────────
@app.post("/v1/monitor")
@app.post("/v2/monitor")
async def monitor_create(body: MonitorRequest):
    try:
        opts = body.scrapeOptions.model_dump() if body.scrapeOptions else None
        mon_id = await monitor.create_monitor(
            body.url, body.intervalSeconds, opts, body.egress
        )
    except Exception as exc:
        log.exception("monitor tạo lỗi")
        applog.event("monitor", "monitor tạo lỗi", level=logging.ERROR, url=body.url, error=str(exc))
        return _err(f"monitor failed: {exc}")
    return {"success": True, "id": mon_id}


@app.get("/v1/monitor")
@app.get("/v2/monitor")
async def monitor_list():
    return {"success": True, "monitors": [monitor.summary(m) for m in monitor.MONITORS.values()]}


@app.get("/v1/monitor/{mon_id}")
@app.get("/v2/monitor/{mon_id}")
async def monitor_get(mon_id: str):
    mon = monitor.MONITORS.get(mon_id)
    if not mon:
        return _err("monitor not found", status=404)
    return {"success": True, "monitor": {k: v for k, v in mon.items() if not k.startswith("_")}}


@app.post("/v1/monitor/{mon_id}/check")
@app.post("/v2/monitor/{mon_id}/check")
async def monitor_check_now(mon_id: str):
    mon = monitor.MONITORS.get(mon_id)
    if not mon:
        return _err("monitor not found", status=404)
    event = await monitor.check_monitor(mon)
    return {"success": True, "changed": event is not None, "event": event}


@app.delete("/v1/monitor/{mon_id}")
@app.delete("/v2/monitor/{mon_id}")
async def monitor_delete(mon_id: str):
    ok = await monitor.delete_monitor(mon_id)
    if not ok:
        return _err("monitor not found", status=404)
    return {"success": True, "status": "deleted"}


# ─── /research (đa-trục, chống bias) ────────────────────────────────────
@app.post("/v1/research")
@app.post("/v2/research")
async def research_endpoint(body: ResearchRequest):
    """Gatherer chống thiên lệch: đa dạng nguồn theo nhiều trục; (tuỳ chọn, cần LLM) dịch query đa ngôn ngữ và so chéo nguồn (`analyze`) → trả `translations`/`analysis`/`warnings`."""
    warnings: list[str] = []
    translations = None
    analysis = None
    try:
        proxy = await egress_mod.resolve_proxy(body.egress)
        languages = body.languages
        # Caller không nêu languages → lấy từ query-intent (ngôn ngữ của các bên liên quan) để vừa
        # DỊCH query đa ngôn ngữ thật, vừa lái trục ngôn ngữ của gatherer. CHỈ kích hoạt khi intent
        # gợi ý đa ngôn ngữ thật (>1 ngôn ngữ, hoặc 1 ngôn ngữ khác tiếng Anh) — query Anh/global
        # mono-lingual giữ nguyên hành vi cũ, khỏi tốn một call dịch vô ích. Fail-open.
        if not (languages and any(l for l in languages)):
            try:
                cand = ((await query_intent.analyze_intent(body.query)) or {}).get("languages") or []
                if len(cand) > 1 or (cand and cand != ["en"]):
                    languages = cand
            except Exception:
                pass
        query_by_lang = None
        # #8: dịch query nếu có ngôn ngữ thật (fail-open trong translate_queries).
        if languages and any(l for l in languages):
            translations, w = await research_llm.translate_queries(body.query, languages)
            query_by_lang = translations
            if w:
                warnings.append(w)
        # #9 cần nội dung thật → ép scrape khi analyze.
        scrape = body.scrape or body.analyze
        sources = await research_mod.research(
            body.query,
            categories=body.categories,
            languages=languages,
            sites=body.sites,
            max_per_domain=body.maxPerDomain,
            limit=body.limit,
            scrape=scrape,
            query_by_lang=query_by_lang,
            proxy=proxy,
        )
        # #9: so chéo nguồn (fail-open trong cross_check).
        if body.analyze:
            analysis, w = await research_llm.cross_check(body.query, sources)
            if w:
                warnings.append(w)
    except Exception as exc:
        log.exception("research lỗi")
        applog.event("research", "research lỗi", level=logging.ERROR,
                     query=body.query, error=str(exc))
        return _err(f"research failed: {exc}")
    return {
        "success": True,
        "query": body.query,
        "stats": research_mod.stats(sources),
        "translations": translations,
        "analysis": analysis,
        "warnings": warnings,
        "sources": sources,
    }
