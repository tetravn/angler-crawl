"""Test /extract gọi LLM nhất quán qua tier smart (LLM_MODEL_SMART)."""
import asyncio

from app import extract, crawl_jobs
from app.config import LLM_MODEL_SMART


def test_extract_dung_tier_smart_va_hoan_tat(monkeypatch):
    captured = {}

    async def fake_scrape(url, formats, only_main):
        return ({"markdown": "nội dung trang"}, None, None)

    async def fake_llm(messages, *, model=None, json_mode=True, timeout=None, **k):
        captured["model"] = model
        captured["json_mode"] = json_mode
        return '{"x": 1}'

    async def fake_persist(job):
        return None

    monkeypatch.setattr(extract.scrape_mod, "scrape", fake_scrape)
    monkeypatch.setattr(extract.clients, "llm_chat", fake_llm)
    monkeypatch.setattr(extract.crawl_jobs, "_persist", fake_persist)

    crawl_jobs.JOBS["t-extract"] = {"id": "t-extract", "status": "scraping", "data": {}}
    try:
        asyncio.run(extract._run("t-extract", ["http://x.com"], "trích xuất", None))
        job = crawl_jobs.JOBS["t-extract"]
        # phải gọi đúng bậc smart (payload lớn), không tự tụt xuống bậc fast
        assert captured["model"] == LLM_MODEL_SMART
        assert captured["json_mode"] is True
        assert job["status"] == "completed"
        assert job["data"] == {"x": 1}
    finally:
        crawl_jobs.JOBS.pop("t-extract", None)
