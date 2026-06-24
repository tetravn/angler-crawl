"""Firecrawl /v1/extract → scrape các URL rồi trích xuất bằng LLM.

Cần cấu hình LLM (OpenAI-compatible) qua env LLM_BASE_URL/LLM_MODEL/LLM_API_KEY.
Chưa cấu hình → job fail với thông báo rõ ràng (endpoint vẫn tồn tại).
"""
import json
import logging

from . import applog, clients, crawl_jobs, scrape as scrape_mod
from .config import LLM_MODEL_SMART, LLM_HTTP_TIMEOUT

log = logging.getLogger("shim.extract")

_SYSTEM = "You extract structured data from web content. Return ONLY a valid JSON object."


def create_extract_job(urls: list[str], prompt: str | None, schema: dict | None) -> str:
    job = crawl_jobs.new_job()
    job["data"] = {}  # extract: data là object (không phải list)
    crawl_jobs.persist_bg(job)
    applog.event("extract", "job tạo", request_id=job["id"], count=len(urls))
    crawl_jobs.spawn(_run(job["id"], urls, prompt, schema))
    return job["id"]


async def _run(
    job_id: str, urls: list[str], prompt: str | None, schema: dict | None
) -> None:
    job = crawl_jobs.JOBS[job_id]
    try:
        # 1) Scrape tối đa 10 URL → gộp markdown.
        chunks: list[str] = []
        for url in urls[:10]:
            try:
                data, _r, _ = await scrape_mod.scrape(url, ["markdown"], True)
                chunks.append(f"# Nguồn: {url}\n\n{data.get('markdown') or ''}")
            except Exception as exc:
                log.warning("extract: lỗi scrape %s: %s", url, exc)
                applog.event("extract", "lỗi scrape url", level=logging.WARNING,
                             request_id=job_id, url=url, error=str(exc))
        content = "\n\n---\n\n".join(chunks)[:60000]

        # 2) Gọi LLM.
        user = prompt or "Trích xuất các thông tin chính."
        if schema:
            user += f"\n\nTuân theo JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
        user += f"\n\nNỘI DUNG:\n{content}"
        applog.event("extract", "gọi LLM", request_id=job_id, urls=len(chunks))
        out = await clients.llm_chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            model=LLM_MODEL_SMART, json_mode=True, timeout=LLM_HTTP_TIMEOUT)
        try:
            extracted = clients.loads_json(out)
        except Exception:
            extracted = {"raw": out}

        job["data"] = extracted
        job["total"] = 1
        job["completed"] = 1
        job["status"] = "completed"
        applog.event("extract", "job xong", request_id=job_id)
        await crawl_jobs._persist(job)
    except Exception as exc:
        log.exception("extract job %s thất bại", job_id)
        applog.event("extract", "job thất bại", level=logging.ERROR, request_id=job_id, error=str(exc))
        job["status"] = "failed"
        job["error"] = str(exc)
        await crawl_jobs._persist(job)
