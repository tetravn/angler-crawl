import asyncio

from app import agent
from app import crawl_jobs


def test_run_agent_emits_steps_and_done(monkeypatch):
    async def fake_avail():
        return True

    async def fake_plan(prompt, obs, history):
        return {"action": "done", "answer": "R"}, None

    async def fake_verify(prompt, page):
        return True, "ok"

    async def fake_browser(url, *, session_id, js_code=None, js_only=False, wait_for_ms=0, proxy=None):
        return {"markdown": "m", "js_execution_result": {"success": True, "results": [[]]}}

    async def fake_close(sid):
        pass

    async def fake_proxy(e):
        return None

    async def fake_persist(job):
        return None

    monkeypatch.setattr(agent, "_llm_available", fake_avail)
    monkeypatch.setattr(agent, "plan_action", fake_plan)
    monkeypatch.setattr(agent, "verify_done", fake_verify)
    monkeypatch.setattr(agent.clients, "browser_step", fake_browser)
    monkeypatch.setattr(agent.clients, "close_session", fake_close)
    monkeypatch.setattr(agent.egress_mod, "resolve_proxy", fake_proxy)
    monkeypatch.setattr(agent.transform, "markdown_of", lambda r, o: r.get("markdown", ""))
    monkeypatch.setattr(crawl_jobs, "_persist", fake_persist)

    events = []

    async def emit(ev):
        events.append(ev)

    job = crawl_jobs.new_job()
    asyncio.run(agent.run_agent(job["id"], "http://x", "g",
                                {"url": "http://x", "prompt": "g", "maxSteps": 3, "egress": None},
                                emit=emit))
    types = [e["type"] for e in events]
    assert "step" in types
    assert events[-1]["type"] == "done" and "data" in events[-1]
