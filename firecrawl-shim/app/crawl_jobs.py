"""Job crawl bất đồng bộ.

Dùng deep-crawl native của Crawl4AI (BFSDeepCrawlStrategy) để khám phá + lấy
nội dung trong 1 lần gọi (nhanh, discovery tốt). Trang nào về dạng bị Cloudflare
chặn thì re-fetch riêng qua FlareSolverr (hybrid) để vẫn bypass được CF.

Job lưu trong RAM (JOBS) + ghi xuống SQLite (store) để sống sót qua restart.
"""
import asyncio
import logging
import re
import secrets
import time
from urllib.parse import urlparse

from . import applog, clients, scrape as scrape_mod, store, transform
from .config import CRAWL_CONCURRENCY, JOB_TTL_SECONDS

log = logging.getLogger("shim.crawl")

# id -> job dict (cache RAM; nguồn bền vững là SQLite qua store)
JOBS: dict[str, dict] = {}

# Giữ reference task nền (asyncio cảnh báo: task không được giữ ref có thể bị GC giết giữa chừng).
_BG_TASKS: set = set()


def spawn(coro):
    """Tạo task nền + giữ reference tới khi xong (tránh GC nuốt task fire-and-forget)."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


def persist_bg(job: dict):
    """Ghi job xuống SQLite ở nền, có giữ reference. Dùng cho các caller fire-and-forget."""
    return spawn(_persist(job))


def _norm(u: str) -> str:
    """Chuẩn hoá URL để dedupe: bỏ fragment + 1 dấu / ở cuối."""
    u = u.split("#")[0]
    return u[:-1] if u.endswith("/") else u


def _path_ok(url: str, includes: list[str], excludes: list[str]) -> bool:
    path = urlparse(url).path or "/"
    if excludes and any(re.search(p, path) for p in excludes):
        return False
    if includes and not any(re.search(p, path) for p in includes):
        return False
    return True


def new_job() -> dict:
    now = time.time()
    job = {
        "id": secrets.token_hex(12),
        "status": "scraping",
        "total": 0,
        "completed": 0,
        "creditsUsed": 0,
        "expiresAt": time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now + JOB_TTL_SECONDS)
        ),
        "data": [],
        "error": None,
        "_expires_ts": now + JOB_TTL_SECONDS,
    }
    JOBS[job["id"]] = job
    return job


def cancel_job(job_id: str) -> bool:
    """Đánh dấu huỷ (best-effort — vòng lặp sẽ dừng ở bước kế tiếp)."""
    job = JOBS.get(job_id)
    if not job or job["status"] in ("completed", "failed", "cancelled"):
        return False
    job["status"] = "cancelled"
    persist_bg(job)
    return True


def create_job(req: dict) -> str:
    job = new_job()
    persist_bg(job)
    applog.event("crawl", "job tạo", request_id=job["id"], url=req.get("url"))
    spawn(_run(job["id"], req))
    return job["id"]


def create_batch_job(urls: list[str], scrape_options: dict | None, proxy: str | None = None) -> str:
    job = new_job()
    persist_bg(job)
    applog.event("batch", "job tạo", request_id=job["id"], count=len(urls))
    spawn(_run_batch(job["id"], urls, scrape_options or {}, proxy))
    return job["id"]


async def _run_batch(job_id: str, urls: list[str], opts: dict, proxy: str | None = None) -> None:
    """Scrape song song một danh sách URL cố định (không BFS)."""
    job = JOBS[job_id]
    try:
        formats = opts.get("formats") or ["markdown"]
        only_main = opts.get("onlyMainContent", True)
        # dedupe giữ thứ tự
        seen: set[str] = set()
        targets = [u for u in urls if not (u in seen or seen.add(u))]
        job["total"] = len(targets)
        await _persist(job)

        sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

        async def one(url: str) -> dict | None:
            if job["status"] == "cancelled":
                return None
            async with sem:
                if job["status"] == "cancelled":   # re-check sau khi chờ slot: hủy giữa batch có hiệu lực
                    return None
                try:
                    data, _r, _ = await scrape_mod.scrape(
                        url, formats, only_main,
                        wait_for_ms=opts.get("waitFor", 0),
                        timeout_ms=opts.get("timeout", 0),
                        headers=opts.get("headers"),
                        proxy=proxy,
                        fallback=opts.get("fallback"),
                    )
                    return data
                except Exception as exc:
                    log.warning("batch: lỗi scrape %s: %s", url, exc)
                    applog.event("batch", "lỗi scrape url", level=logging.WARNING,
                                 request_id=job_id, url=url, error=str(exc))
                    return None

        for data in await asyncio.gather(*[one(u) for u in targets]):
            if data is not None:
                job["data"].append(data)
                job["completed"] += 1
                job["creditsUsed"] += 1
        if job["status"] != "cancelled":
            job["status"] = "completed"
            applog.event("batch", "job xong", request_id=job_id,
                         total=job["total"], completed=job["completed"])
        await _persist(job)
    except Exception as exc:
        log.exception("batch job %s thất bại", job_id)
        applog.event("batch", "job thất bại", level=logging.WARNING, request_id=job_id, error=str(exc))
        job["status"] = "failed"
        job["error"] = str(exc)
        await _persist(job)


async def _persist(job: dict) -> None:
    try:
        await store.save_job(job)
    except Exception:
        log.exception("không persist được job %s", job.get("id"))


async def _maybe_bypass_cf(result: dict, fallback_url: str, only_main: bool, proxy: str | None = None, job_id: str | None = None) -> dict:
    """Nếu result bị Cloudflare chặn → giải bằng FlareSolverr rồi render lại.

    proxy: truyền vào FlareSolverr để giải CF qua proxy per-request.
    fetch_page("raw://...") không cần proxy — đã có HTML sẵn, chỉ render local.
    """
    if not transform.is_cloudflare_blocked(result):
        return result
    url = result.get("url") or fallback_url
    try:
        solution = (await clients.flaresolverr_get(url, proxy=proxy)).get("solution") or {}
        html = solution.get("response")
        if html:
            # raw:// chỉ render HTML đã có → không cần proxy.
            fixed = await clients.fetch_page(
                "raw://" + html, only_main_content=only_main
            )
            fixed["url"] = url
            fixed["status_code"] = solution.get("status") or 200
            return fixed
    except Exception as exc:
        log.warning("crawl: FlareSolverr lỗi cho %s: %s", url, exc)
        applog.event("crawl", "FlareSolverr lỗi", level=logging.WARNING, url=url, error=str(exc), request_id=job_id)
    return result


async def _run(job_id: str, req: dict) -> None:
    job = JOBS[job_id]
    try:
        seed = req["url"]
        limit = max(1, int(req.get("limit") or 10))
        max_depth = int(req.get("maxDepth", 2))
        includes = req.get("includePaths") or []
        excludes = req.get("excludePaths") or []
        allow_external = bool(req.get("allowExternalLinks", False))
        opts = req.get("scrapeOptions") or {}
        formats = opts.get("formats") or ["markdown"]
        only_main = opts.get("onlyMainContent", True)
        # Đọc proxy per-request (endpoint đã gắn vào req["_proxy"] trước khi gọi create_job).
        proxy: str | None = req.get("_proxy")

        # 1) Deep-crawl native: 1 lần gọi → nhiều trang.
        results = await clients.fetch_deep(
            seed,
            max_depth=max_depth,
            max_pages=limit,
            include_external=allow_external,
            only_main_content=only_main,
            proxy=proxy,
        )

        # 2) Lọc include/exclude + dedupe + cắt theo limit.
        seen: set[str] = set()
        kept: list[dict] = []
        for r in results:
            url = r.get("url") or seed
            key = _norm(url)
            if key in seen or not _path_ok(url, includes, excludes):
                continue
            seen.add(key)
            kept.append(r)
            if len(kept) >= limit:
                break

        job["total"] = len(kept)
        await _persist(job)

        # 3) CF hybrid + map sang schema Firecrawl (re-fetch song song trang bị chặn).
        sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

        async def finalize(r: dict) -> dict:
            async with sem:
                r = await _maybe_bypass_cf(r, seed, only_main, proxy, job_id=job_id)
            src = r.get("url") or seed
            return transform.to_firecrawl_data(r, formats, only_main, src)

        for data in await asyncio.gather(*[finalize(r) for r in kept]):
            if job["status"] == "cancelled":
                break
            job["data"].append(data)
            job["completed"] += 1
            job["creditsUsed"] += 1

        if job["status"] != "cancelled":
            job["status"] = "completed"
            applog.event("crawl", "job xong", request_id=job_id,
                         total=job["total"], completed=job["completed"])
        await _persist(job)
    except Exception as exc:
        log.exception("crawl job %s thất bại", job_id)
        applog.event("crawl", "job thất bại", level=logging.WARNING, request_id=job_id, error=str(exc))
        job["status"] = "failed"
        job["error"] = str(exc)
        await _persist(job)
