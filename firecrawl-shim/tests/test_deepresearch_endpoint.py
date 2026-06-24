import asyncio

from app import main as main_mod, models, crawl_jobs


class _FakeReq:
    class url:
        scheme = "http"
    headers = {"host": "localhost:17300"}


def test_post_creates_job(monkeypatch):
    monkeypatch.setattr(main_mod.deepresearch, "create_deep_research_job", lambda p: "JOB123")
    body = models.DeepResearchRequest(query="ai là ai")
    out = asyncio.run(main_mod.deep_research_endpoint(body, _FakeReq()))
    assert out["success"] is True
    assert out["id"] == "JOB123"
    assert out["url"].endswith("/v1/deep-research/JOB123")


def test_post_passes_params(monkeypatch):
    cap = {}
    monkeypatch.setattr(main_mod.deepresearch, "create_deep_research_job",
                        lambda p: cap.update(p) or "J")
    body = models.DeepResearchRequest(query="q", maxIterations=5, egress="vpn")
    asyncio.run(main_mod.deep_research_endpoint(body, _FakeReq()))
    assert cap["query"] == "q" and cap["maxIterations"] == 5 and cap["egress"] == "vpn"


def test_get_status_not_found():
    out = asyncio.run(main_mod.deep_research_status("nope"))
    assert out.status_code == 404


def test_get_status_returns_job_body():
    job = crawl_jobs.new_job()
    job["status"] = "completed"
    job["data"] = {"answer": "hi"}
    out = asyncio.run(main_mod.deep_research_status(job["id"]))
    assert out["status"] == "completed" and out["data"] == {"answer": "hi"}


def test_delete_cancels():
    job = crawl_jobs.new_job()
    out = asyncio.run(main_mod.deep_research_cancel(job["id"]))
    assert out["success"] is True and out["status"] == "cancelled"
    assert crawl_jobs.JOBS[job["id"]]["status"] == "cancelled"


def test_delete_not_found():
    out = asyncio.run(main_mod.deep_research_cancel("nope"))
    assert out.status_code == 404
