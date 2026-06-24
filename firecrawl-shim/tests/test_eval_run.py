import asyncio

from app.eval import run
from app import crawl_jobs


def _common(monkeypatch):
    async def fake_scrape_text(url):
        return "nội dung nguồn"
    monkeypatch.setattr(run, "_scrape_text", fake_scrape_text)


def test_run_extraction_aggregates(monkeypatch):
    async def fake_extract_run(job_id, urls, prompt, schema):
        j = crawl_jobs.JOBS[job_id]
        j["status"] = "completed"
        j["data"] = {"creator": "Guido"}

    async def fake_judge(expected, extracted):
        return 2, 2, []

    monkeypatch.setattr(run.extract, "_run", fake_extract_run)
    monkeypatch.setattr(run.grade, "judge_extraction", fake_judge)
    out = asyncio.run(run._run_extraction([{"url": "u", "expected": {"a": 1, "b": 2}}]))
    assert out["accuracy"] == 1.0
    assert out["correct"] == 2 and out["total"] == 2
    assert out["cases"][0]["wrong"] == []


def test_run_extraction_case_error_continues(monkeypatch):
    async def boom_run(job_id, urls, prompt, schema):
        raise RuntimeError("scrape down")
    monkeypatch.setattr(run.extract, "_run", boom_run)
    out = asyncio.run(run._run_extraction([{"url": "u", "expected": {"a": 1}}]))
    # lỗi ở bất cứ đâu trong try → tot_n vẫn tính số trường expected (mẫu số giữ nguyên)
    assert out["total"] == 1
    assert "error" in out["cases"][0]


def test_run_faithfulness_aggregates(monkeypatch):
    _common(monkeypatch)

    async def fake_dr_run(job_id, params):
        j = crawl_jobs.JOBS[job_id]
        j["status"] = "completed"
        j["data"] = {"answer": "Python do Guido tạo ra năm 1991 [1]. Một câu không nguồn ở đây nhé.",
                     "sources": [{"n": 1, "url": "http://a", "title": "A"}]}

    async def fake_judge_claim(claim, texts):
        return True

    monkeypatch.setattr(run.deepresearch, "_run", fake_dr_run)
    monkeypatch.setattr(run.grade, "judge_claim", fake_judge_claim)
    out = asyncio.run(run._run_faithfulness([{"query": "q"}]))
    # mẫu số = cited (1) + uncited (1) = 2 → faithfulness = 0.5
    assert out["faithfulness"] == 0.5
    assert out["supported"] == 1 and out["cited"] == 1
    assert out["substantial"] == 2
    assert len(out["cases"][0]["uncited"]) == 1        # câu không nguồn


def test_run_faithfulness_lists_fabricated(monkeypatch):
    _common(monkeypatch)

    async def fake_dr_run(job_id, params):
        j = crawl_jobs.JOBS[job_id]
        j["status"] = "completed"
        j["data"] = {"answer": "Một khẳng định có vẻ đúng nhưng thật ra bịa hoàn toàn [1].",
                     "sources": [{"n": 1, "url": "http://a", "title": "A"}]}

    async def fake_judge_claim(claim, texts):
        return False
    monkeypatch.setattr(run.deepresearch, "_run", fake_dr_run)
    monkeypatch.setattr(run.grade, "judge_claim", fake_judge_claim)
    out = asyncio.run(run._run_faithfulness([{"query": "q"}]))
    assert out["faithfulness"] == 0.0
    assert len(out["cases"][0]["fabricated"]) == 1


def test_run_extraction_judge_error_keeps_denominator(monkeypatch):
    """judge_extraction raise → tot_n vẫn tính đủ số trường expected (mẫu số không bị thu hẹp)."""
    async def fake_extract_run(job_id, urls, prompt, schema):
        j = crawl_jobs.JOBS[job_id]
        j["status"] = "completed"
        j["data"] = {"a": 1, "b": 2}

    async def boom_judge(expected, extracted):
        raise RuntimeError("LLM lỗi")

    monkeypatch.setattr(run.extract, "_run", fake_extract_run)
    monkeypatch.setattr(run.grade, "judge_extraction", boom_judge)
    out = asyncio.run(run._run_extraction([{"url": "u", "expected": {"a": 1, "b": 2}}]))
    # mẫu số phải là 2 (số trường expected), không phải 0
    assert out["total"] == 2
    assert "error" in out["cases"][0]
