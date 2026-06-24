import asyncio

from app import main as main_mod, models, crawl_jobs


class _FakeReq:
    class url:
        scheme = "http"
    headers = {"host": "localhost:17300"}


def test_post_creates_agent_job(monkeypatch):
    monkeypatch.setattr(main_mod.agent, "create_agent_job", lambda p: "AJOB")
    body = models.AgentRequest(url="http://x", prompt="tìm trang Pricing")
    out = asyncio.run(main_mod.agent_endpoint(body, _FakeReq()))
    assert out["success"] is True and out["id"] == "AJOB"
    assert out["url"].endswith("/v1/agent/AJOB")


def test_post_passes_params(monkeypatch):
    cap = {}
    monkeypatch.setattr(main_mod.agent, "create_agent_job", lambda p: cap.update(p) or "J")
    body = models.AgentRequest(url="http://x", prompt="g", maxSteps=3, egress="vpn")
    asyncio.run(main_mod.agent_endpoint(body, _FakeReq()))
    assert cap["url"] == "http://x" and cap["prompt"] == "g" and cap["maxSteps"] == 3 and cap["egress"] == "vpn"


def test_get_agent_status_not_found():
    out = asyncio.run(main_mod.agent_status("nope"))
    assert out.status_code == 404


def test_get_agent_status_ok():
    job = crawl_jobs.new_job()
    job["status"] = "completed"
    job["data"] = {"result": "done", "verified": True}
    out = asyncio.run(main_mod.agent_status(job["id"]))
    assert out["status"] == "completed" and out["data"]["verified"] is True


def test_delete_agent_cancels():
    job = crawl_jobs.new_job()
    out = asyncio.run(main_mod.agent_cancel(job["id"]))
    assert out["success"] is True and crawl_jobs.JOBS[job["id"]]["status"] == "cancelled"


def test_delete_agent_not_found():
    out = asyncio.run(main_mod.agent_cancel("nope"))
    assert out.status_code == 404
