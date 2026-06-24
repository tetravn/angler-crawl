import asyncio

from app import research_llm


def _patch_llm(monkeypatch, *, returns=None, raises=None):
    async def fake(messages, **kw):
        _patch_llm.last_kw = kw
        if raises:
            raise raises
        return returns
    _patch_llm.last_kw = None
    monkeypatch.setattr(research_llm.clients, "llm_chat", fake)


def test_translate_success(monkeypatch):
    _patch_llm(monkeypatch, returns='{"vi": "trí tuệ nhân tạo", "en": "AI"}')
    out, warn = asyncio.run(research_llm.translate_queries("AI", [None, "vi", "en"]))
    assert warn is None
    assert out[None] == "AI"           # None → query gốc
    assert out["vi"] == "trí tuệ nhân tạo"
    assert out["en"] == "AI"
    assert _patch_llm.last_kw["model"] == research_llm.LLM_MODEL_FAST


def test_translate_no_targets_skips_llm(monkeypatch):
    called = {"n": 0}

    async def fake(messages, **kw):
        called["n"] += 1
        return "{}"
    monkeypatch.setattr(research_llm.clients, "llm_chat", fake)
    out, warn = asyncio.run(research_llm.translate_queries("AI", [None]))
    assert out == {None: "AI"}
    assert warn is None
    assert called["n"] == 0            # không lang thật → không gọi LLM


def test_translate_llm_error_fallback(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("LLM down"))
    out, warn = asyncio.run(research_llm.translate_queries("AI", [None, "vi"]))
    assert out == {None: "AI", "vi": "AI"}   # fallback query gốc
    assert warn and "translate_queries" in warn


def test_translate_bad_json_fallback(monkeypatch):
    _patch_llm(monkeypatch, returns="not json")
    out, warn = asyncio.run(research_llm.translate_queries("AI", ["vi"]))
    assert out == {"vi": "AI"}
    assert warn and "translate_queries" in warn


def test_translate_missing_lang_uses_original(monkeypatch):
    _patch_llm(monkeypatch, returns='{"vi": "AI tiếng việt"}')   # thiếu "en"
    out, warn = asyncio.run(research_llm.translate_queries("AI", ["vi", "en"]))
    assert out["vi"] == "AI tiếng việt"
    assert out["en"] == "AI"            # thiếu → query gốc
    assert warn is None


def _items(*types):
    return [{"url": f"http://s{i}", "sourceType": t,
             "markdown": "nội dung " * 100, "domain": f"s{i}"}
            for i, t in enumerate(types)]


def test_cross_check_no_content_returns_warning(monkeypatch):
    items = [{"url": "http://a", "sourceType": "news", "markdown": "", "blocked": True}]
    out, warn = asyncio.run(research_llm.cross_check("q", items))
    assert out is None
    assert warn and "không có nguồn" in warn


def test_cross_check_success(monkeypatch):
    _patch_llm(monkeypatch, returns='{"consensus": ["x"], "disagreements": [], "outliers": []}')
    out, warn = asyncio.run(research_llm.cross_check("q", _items("news", "academic")))
    assert out == {"consensus": ["x"], "disagreements": [], "outliers": []}
    assert warn is None
    assert _patch_llm.last_kw["model"] == research_llm.LLM_MODEL_SMART


def test_cross_check_caps_sources_with_warning(monkeypatch):
    _patch_llm(monkeypatch, returns='{"consensus": [], "disagreements": [], "outliers": []}')
    items = _items(*(["news"] * 12))     # 12 nguồn có nội dung
    out, warn = asyncio.run(research_llm.cross_check("q", items, max_sources=8))
    assert out is not None
    assert warn and "8/12" in warn


def test_cross_check_llm_error(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("LLM down"))
    out, warn = asyncio.run(research_llm.cross_check("q", _items("news")))
    assert out is None
    assert warn and "cross_check" in warn


def test_select_balances_by_source_type():
    items = (_items(*(["news"] * 5)) + _items("academic"))
    sel, n = research_llm._select_for_cross_check(items, 2)
    assert n == 6
    assert {s["sourceType"] for s in sel} == {"news", "academic"}   # cân bằng, không toàn news
