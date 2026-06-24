import asyncio

from app import main as main_mod, models


def _wire(monkeypatch, *, translate=None, cross=None):
    cap = {}

    async def fake_research(query, **kw):
        cap.update(kw)
        cap["query"] = query
        return [{"url": "http://a", "title": "A", "description": "d",
                 "domain": "a", "sourceType": "news"}]

    async def fake_proxy(e):
        return None

    async def fake_intent(q):
        # Mặc định: query Anh/global mono-lingual (không kích hoạt dịch). Test cần khác thì override.
        return {"languages": ["en"], "geos": [], "is_global": True}

    monkeypatch.setattr(main_mod.research_mod, "research", fake_research)
    monkeypatch.setattr(main_mod.egress_mod, "resolve_proxy", fake_proxy)
    monkeypatch.setattr(main_mod.query_intent, "analyze_intent", fake_intent)
    if translate:
        monkeypatch.setattr(main_mod.research_llm, "translate_queries", translate)
    if cross:
        monkeypatch.setattr(main_mod.research_llm, "cross_check", cross)
    return cap


def test_endpoint_analyze_forces_scrape_and_returns_fields(monkeypatch):
    async def translate(q, langs):
        return ({None: q, "vi": "dịch"}, None)

    async def cross(q, items, **kw):
        return ({"consensus": ["c"]}, None)

    cap = _wire(monkeypatch, translate=translate, cross=cross)
    body = models.ResearchRequest(query="q", languages=["vi"], analyze=True)
    out = asyncio.run(main_mod.research_endpoint(body))
    assert cap["scrape"] is True                       # analyze ép scrape
    assert cap["query_by_lang"] == {None: "q", "vi": "dịch"}
    assert out["translations"]["vi"] == "dịch"
    assert out["analysis"] == {"consensus": ["c"]}
    assert out["warnings"] == []
    assert "sources" in out and "stats" in out


def test_endpoint_no_llm_fields_unchanged(monkeypatch):
    cap = _wire(monkeypatch)
    body = models.ResearchRequest(query="q")           # không languages/analyze
    out = asyncio.run(main_mod.research_endpoint(body))
    assert cap["scrape"] is False
    assert cap["query_by_lang"] is None
    assert out["translations"] is None
    assert out["analysis"] is None
    assert out["warnings"] == []


def test_endpoint_collects_warnings(monkeypatch):
    async def translate(q, langs):
        return ({None: q, "vi": q}, "translate_queries: boom")

    cap = _wire(monkeypatch, translate=translate)
    body = models.ResearchRequest(query="q", languages=["vi"])
    out = asyncio.run(main_mod.research_endpoint(body))
    assert out["warnings"] == ["translate_queries: boom"]


def test_endpoint_intent_lai_translate_khi_khong_neu_languages(monkeypatch):
    # Caller KHÔNG truyền languages → intent điền → dịch query theo các ngôn ngữ đó + truyền vào research.
    translated_with = {}

    async def translate(q, langs):
        translated_with["langs"] = langs
        return ({None: q, "vi": "dịch", "en": q}, None)

    async def fake_intent(q):
        return {"languages": ["vi", "en"], "geos": ["vn"], "is_global": False}

    cap = _wire(monkeypatch, translate=translate)
    monkeypatch.setattr(main_mod.query_intent, "analyze_intent", fake_intent)
    asyncio.run(main_mod.research_endpoint(models.ResearchRequest(query="chính sách Việt Nam")))
    assert translated_with["langs"] == ["vi", "en"]   # intent lái translate_queries
    assert cap["languages"] == ["vi", "en"]           # và languages truyền vào research()


def test_endpoint_intent_fail_open(monkeypatch):
    # intent lỗi → languages giữ None → không dịch (hành vi cũ), endpoint KHÔNG raise.
    called = {"translate": False}

    async def translate(q, langs):
        called["translate"] = True
        return ({}, None)

    async def boom(q):
        raise RuntimeError("intent down")

    cap = _wire(monkeypatch, translate=translate)
    monkeypatch.setattr(main_mod.query_intent, "analyze_intent", boom)
    out = asyncio.run(main_mod.research_endpoint(models.ResearchRequest(query="q")))
    assert out["success"] is True
    assert called["translate"] is False
