import asyncio

from app import deepresearch as dr
from app import crawl_jobs


def test_synthesize_uses_stream_when_on_token(monkeypatch):
    got = []

    async def fake_stream(messages, **kw):
        await kw["on_token"]("tok")
        return "ANSWER"

    monkeypatch.setattr(dr.clients, "stream_chat", fake_stream)

    async def on_tok(t):
        got.append(t)

    out = asyncio.run(dr.synthesize("q", [{"url": "u", "title": "t", "markdown": "m"}], on_token=on_tok))
    assert out == "ANSWER" and got == ["tok"]


def test_run_emits_phase_and_done(monkeypatch):
    async def fake_persist(job):
        return None
    monkeypatch.setattr(crawl_jobs, "_persist", fake_persist)

    async def fake_plan(query):
        return ([{"question": "q0", "search_query": "s", "answered": False,
                  "confidence": 0.9, "sources": []}], [])

    async def fake_check(subs, src):
        return subs, []

    async def fake_synth(query, sources, on_token=None):
        if on_token:
            await on_token("partial")
        return "ANS"

    async def fake_proxy(e):
        return None

    async def fake_search(q, **kw):
        return []

    monkeypatch.setattr(dr, "plan_subqueries", fake_plan)
    monkeypatch.setattr(dr, "check_answers", fake_check)
    monkeypatch.setattr(dr, "synthesize", fake_synth)
    monkeypatch.setattr(dr.egress_mod, "resolve_proxy", fake_proxy)
    monkeypatch.setattr(dr.clients, "searxng_search", fake_search)

    events = []

    async def emit(ev):
        events.append(ev)

    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], {"query": "q", "maxIterations": 1, "maxQueries": 1,
                                    "maxSourcesPerQuery": 1, "maxScrapePerIteration": 1,
                                    "egress": None}, emit=emit))
    types = [e["type"] for e in events]
    assert "phase" in types
    assert any(e["type"] == "token" and e["text"] == "partial" for e in events)
    assert events[-1]["type"] == "done" and "data" in events[-1]
