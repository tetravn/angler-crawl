import asyncio

from app import deepresearch as dr


def _patch_llm(monkeypatch, *, returns=None, raises=None):
    async def fake(messages, **kw):
        _patch_llm.last_kw = kw
        if raises:
            raise raises
        return returns
    _patch_llm.last_kw = None
    monkeypatch.setattr(dr.clients, "llm_chat", fake)


def test_plan_success(monkeypatch):
    _patch_llm(monkeypatch, returns='{"subqueries": [{"question": "Ai sáng lập X?", "search_query": "X founder"}, {"question": "Trụ sở X ở đâu?", "search_query": "X headquarters"}]}')
    subs, warn = asyncio.run(dr.plan_subqueries("X là gì"))
    assert warn == []
    assert len(subs) == 2
    assert subs[0]["question"] == "Ai sáng lập X?"
    assert subs[0]["confidence"] == 0.0 and subs[0]["answered"] is False
    assert _patch_llm.last_kw["model"] == dr.LLM_MODEL_SMART


def test_plan_fallback_on_error(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("LLM down"))
    subs, warn = asyncio.run(dr.plan_subqueries("X là gì"))
    assert len(subs) == 1
    assert subs[0]["question"] == "X là gì" and subs[0]["search_query"] == "X là gì"
    assert warn and "plan_subqueries" in warn[0]


def test_plan_bad_json_fallback(monkeypatch):
    _patch_llm(monkeypatch, returns="not json")
    subs, warn = asyncio.run(dr.plan_subqueries("X là gì"))
    assert len(subs) == 1 and warn


def test_check_answers_updates_confidence(monkeypatch):
    _patch_llm(monkeypatch, returns='{"results": [{"index": 0, "answered": true, "confidence": 0.9, '
                                     '"evidence": "approval rating is 40 percent"}]}')
    subs = [{"question": "q0", "search_query": "q0", "answered": False, "confidence": 0.0, "sources": []},
            {"question": "q1", "search_query": "q1", "answered": False, "confidence": 0.0, "sources": []}]
    src = [{"url": "http://a", "title": "A", "markdown": "Trump approval rating is 40 percent in June 2026"}]
    out, warn = asyncio.run(dr.check_answers(subs, src))
    assert warn == []
    assert out[0]["confidence"] == 0.9 and out[0]["answered"] is True   # evidence bám nguồn → giữ
    assert out[1]["confidence"] == 0.0


def test_check_answers_rejects_unsupported_evidence(monkeypatch):
    # Model phán answered nhưng quote KHÔNG có trong nguồn → gate hạ xuống chưa-trả-lời.
    _patch_llm(monkeypatch, returns='{"results": [{"index": 0, "answered": true, "confidence": 0.95, '
                                    '"evidence": "the unemployment rate fell sharply worldwide"}]}')
    subs = [{"question": "q0", "search_query": "q0", "answered": False, "confidence": 0.0, "sources": []}]
    src = [{"url": "http://a", "title": "A", "markdown": "This page is about cooking pasta and tomatoes."}]
    out, _ = asyncio.run(dr.check_answers(subs, src))
    assert out[0]["answered"] is False
    assert out[0]["confidence"] < dr.MIN_CONF      # bị hạ dưới ngưỡng để vòng sau tìm tiếp


def test_check_answers_does_not_lower(monkeypatch):
    _patch_llm(monkeypatch, returns='{"results": [{"index": 0, "answered": false, "confidence": 0.2}]}')
    subs = [{"question": "q0", "search_query": "q0", "answered": True, "confidence": 0.9, "sources": []}]
    src = [{"url": "http://a", "title": "A", "markdown": "content"}]
    out, _ = asyncio.run(dr.check_answers(subs, src))
    assert out[0]["confidence"] == 0.9      # không tụt


def test_check_answers_no_sources_noop(monkeypatch):
    subs = [{"question": "q0", "search_query": "q0", "answered": False, "confidence": 0.0, "sources": []}]
    out, warn = asyncio.run(dr.check_answers(subs, []))
    assert out is subs and warn == []


def test_check_answers_error_keeps(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("boom"))
    subs = [{"question": "q0", "search_query": "q0", "answered": False, "confidence": 0.0, "sources": []}]
    out, warn = asyncio.run(dr.check_answers(subs, [{"url": "http://a", "title": "A", "markdown": "c"}]))
    assert out[0]["confidence"] == 0.0 and warn and "check_answers" in warn[0]


def test_alt_queries_success(monkeypatch):
    _patch_llm(monkeypatch, returns='{"queries": ["alt one", "alt two"]}')
    pending = [{"question": "q0", "search_query": "orig", "answered": False, "confidence": 0.0, "sources": []}]
    qs, warn = asyncio.run(dr.alt_queries(pending))
    assert qs == ["alt one", "alt two"] and warn == []


def test_alt_queries_fallback(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("boom"))
    pending = [{"question": "q0", "search_query": "orig", "answered": False, "confidence": 0.0, "sources": []}]
    qs, warn = asyncio.run(dr.alt_queries(pending))
    assert qs == ["orig"] and warn and "alt_queries" in warn[0]
