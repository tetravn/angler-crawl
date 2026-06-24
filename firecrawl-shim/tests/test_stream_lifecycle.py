"""Regression tests cho FIX 1: streaming job lifecycle.

Kiểm tra rằng khi run_agent / deepresearch._run bị ngắt đột ngột (CancelledError),
job kết thúc với status 'cancelled' (KHÔNG 'scraping') và close_session được gọi.
"""
import asyncio

import pytest

from app import agent, crawl_jobs, deepresearch


# ─── Helpers dùng chung ────────────────────────────────────────────────────

def _noop_persist(job):
    return None


def _wire_agent(monkeypatch, *, plan_raises_cancelled=True):
    """Wire fake dependencies cho agent.run_agent, plan_action ném CancelledError."""
    state = {"closed": 0}

    async def fake_avail():
        return True

    async def fake_plan(prompt, obs, history):
        if plan_raises_cancelled:
            raise asyncio.CancelledError()
        return {"action": "done", "answer": "ok"}, None

    async def fake_verify(prompt, page_text):
        return True, "ok"

    async def fake_browser(url, *, session_id, js_code=None, js_only=False, wait_for_ms=0, proxy=None):
        return {"markdown": "page", "js_execution_result": {"success": True, "results": [[{"idx": 0, "tag": "a", "text": "x"}]]}}

    async def fake_close(sid):
        state["closed"] += 1

    async def fake_proxy(e):
        return None

    monkeypatch.setattr(agent, "_llm_available", fake_avail)
    monkeypatch.setattr(agent, "plan_action", fake_plan)
    monkeypatch.setattr(agent, "verify_done", fake_verify)
    monkeypatch.setattr(agent.clients, "browser_step", fake_browser)
    monkeypatch.setattr(agent.clients, "close_session", fake_close)
    monkeypatch.setattr(agent.egress_mod, "resolve_proxy", fake_proxy)
    monkeypatch.setattr(agent.transform, "markdown_of", lambda r, o: r.get("markdown", ""))
    monkeypatch.setattr(crawl_jobs, "_persist", _noop_persist)
    return state


# ─── Test 1: run_agent bị ngắt bởi CancelledError trong plan_action ───────

def test_run_agent_cancel_leaves_cancelled_status(monkeypatch):
    """CancelledError từ plan_action → job['status'] == 'cancelled', close_session được gọi."""
    state = _wire_agent(monkeypatch, plan_raises_cancelled=True)
    job = crawl_jobs.new_job()
    # job bắt đầu ở 'scraping'
    assert job["status"] == "scraping"

    # CancelledError sẽ lan ra asyncio.run — bắt lại
    with pytest.raises((asyncio.CancelledError, Exception)):
        asyncio.run(agent.run_agent(job["id"], "http://x", "goal",
                                    {"url": "http://x", "prompt": "goal",
                                     "maxSteps": 5, "egress": None}))

    # Quan trọng: KHÔNG còn 'scraping' — phải là 'cancelled'
    assert job["status"] == "cancelled", f"expected 'cancelled', got '{job['status']}'"
    # close_session phải được gọi
    assert state["closed"] == 1


# ─── Test 2: deepresearch._run bị ngắt bởi CancelledError ────────────────

def test_deepresearch_run_cancel_leaves_cancelled_status(monkeypatch):
    """CancelledError trong plan_subqueries → deepresearch job['status'] == 'cancelled'."""
    state = {"persisted": 0}

    async def fake_plan_sub(query):
        raise asyncio.CancelledError()

    async def fake_persist(job):
        state["persisted"] += 1

    monkeypatch.setattr(deepresearch, "plan_subqueries", fake_plan_sub)
    monkeypatch.setattr(crawl_jobs, "_persist", fake_persist)

    job = crawl_jobs.new_job()
    assert job["status"] == "scraping"

    params = {
        "query": "test",
        "maxIterations": 2,
        "maxQueries": 3,
        "maxSourcesPerQuery": 3,
        "maxScrapePerIteration": 5,
        "egress": None,
    }

    with pytest.raises((asyncio.CancelledError, Exception)):
        asyncio.run(deepresearch._run(job["id"], params))

    # Phải là 'cancelled', KHÔNG 'scraping'
    assert job["status"] == "cancelled", f"expected 'cancelled', got '{job['status']}'"
