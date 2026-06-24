import asyncio

from app import research


def test_is_low_value_catches_junk():
    assert research.is_low_value("https://facebook.com/x/posts/1")
    assert research.is_low_value("https://www.chatgpt.com/share/abc")
    assert research.is_low_value("https://dictionary.cambridge.org/dictionary/english/executive")
    assert research.is_low_value("https://calendar-365.com/2026")


def test_is_low_value_keeps_real_sources():
    assert not research.is_low_value("https://www.nytimes.com/article")
    assert not research.is_low_value("https://en.wikipedia.org/wiki/Trump")
    assert not research.is_low_value("https://nature.com/articles/x")
    assert not research.is_low_value("https://congress.gov/bill/939")


def _patch_search(monkeypatch):
    """Ghi lại các query đã gửi tới searxng; trả rỗng để bỏ qua phần còn lại."""
    seen = []

    async def fake_search(q, *, limit=10, lang=None, categories=None):
        seen.append((q, lang, categories))
        return []

    monkeypatch.setattr(research.clients, "searxng_search", fake_search)
    return seen


def test_research_uses_translated_query_per_lang(monkeypatch):
    seen = _patch_search(monkeypatch)
    qbl = {"vi": "AI tiếng việt", "en": "AI english"}
    asyncio.run(research.research(
        "AI", categories=["general"], languages=["vi", "en"], query_by_lang=qbl))
    sent = {(lang): q for (q, lang, _cat) in seen}
    assert sent["vi"] == "AI tiếng việt"
    assert sent["en"] == "AI english"


def test_research_no_map_uses_original_query(monkeypatch):
    seen = _patch_search(monkeypatch)
    asyncio.run(research.research(
        "AI", categories=["general"], languages=["vi", "en"]))   # query_by_lang=None
    for (q, _lang, _cat) in seen:
        assert q == "AI"


def test_research_rank_va_intent_languages(monkeypatch):
    import asyncio
    from app import research

    called = {"langs": []}

    async def fake_searxng(q, *, limit=20, lang=None, categories=None):
        called["langs"].append(lang)
        # arxiv trước (position-relevance cao hơn) → test xác nhận academic ở đầu ra sau ranking
        return [
            {"url": "https://arxiv.org/p", "title": "paper", "content": "y"},
            {"url": "https://blog.com/a", "title": "blog", "content": "x"},
        ]

    async def fake_intent(q):
        return {"languages": ["vi"], "geos": ["vn"], "is_global": False}

    monkeypatch.setattr(research.clients, "searxng_search", fake_searxng)
    monkeypatch.setattr(research.query_intent, "analyze_intent", fake_intent)
    out = asyncio.run(research.research("test", categories=["general"]))
    assert "vi" in called["langs"]                       # languages lấy từ intent khi caller không truyền
    assert out and out[0]["sourceType"] == "academic"    # arxiv (academic) rank lên đầu
    assert all("sourceType" in r for r in out)
    assert all(set(r) == {"url", "title", "description", "domain", "sourceType"} for r in out)  # schema sạch


def test_research_intent_fail_open(monkeypatch):
    async def fake_searxng(q, *, limit=20, lang=None, categories=None):
        return [{"url": "https://a.com/x", "title": "t", "content": "c"}]

    async def boom(q):
        raise RuntimeError("intent down")

    monkeypatch.setattr(research.clients, "searxng_search", fake_searxng)
    monkeypatch.setattr(research.query_intent, "analyze_intent", boom)
    out = asyncio.run(research.research("test", categories=["general"]))  # KHÔNG raise
    assert out and out[0]["url"] == "https://a.com/x"
    assert all(set(r) == {"url", "title", "description", "domain", "sourceType"} for r in out)
