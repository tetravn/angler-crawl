"""Test _run_batch: dedupe giữ thứ tự + hủy giữa chừng có hiệu lực (regression A2)."""
import asyncio

from app import crawl_jobs


async def _fake_persist(job):
    return None


def test_run_batch_dedupe_giu_thu_tu(monkeypatch):
    monkeypatch.setattr(crawl_jobs, "_persist", _fake_persist)
    seen = []

    async def fake_scrape(url, *a, **k):
        seen.append(url)
        return ({"markdown": url, "metadata": {}}, {}, False)
    monkeypatch.setattr(crawl_jobs.scrape_mod, "scrape", fake_scrape)
    job = crawl_jobs.new_job()
    asyncio.run(crawl_jobs._run_batch(job["id"], ["a", "b", "a", "c"], {}, None))
    assert seen == ["a", "b", "c"]                 # "a" trùng bị bỏ, thứ tự giữ nguyên
    assert job["completed"] == 3


def test_run_batch_cancel_giua_chung_chan_scrape(monkeypatch):
    """A2: với concurrency=1, hủy sau URL đầu → các URL còn chờ slot KHÔNG bị scrape (check status TRONG sem)."""
    monkeypatch.setattr(crawl_jobs, "_persist", _fake_persist)
    monkeypatch.setattr(crawl_jobs, "CRAWL_CONCURRENCY", 1)
    job = crawl_jobs.new_job()
    jid = job["id"]
    scraped = []

    async def fake_scrape(url, *a, **k):
        scraped.append(url)
        crawl_jobs.JOBS[jid]["status"] = "cancelled"   # hủy ngay sau URL đầu tiên
        return ({"markdown": url, "metadata": {}}, {}, False)
    monkeypatch.setattr(crawl_jobs.scrape_mod, "scrape", fake_scrape)
    asyncio.run(crawl_jobs._run_batch(jid, ["u1", "u2", "u3"], {}, None))
    assert scraped == ["u1"]               # u2/u3 bị chặn trong sem sau khi hủy
    assert job["status"] == "cancelled"
