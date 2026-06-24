import asyncio

from app import scrape


async def _anoop(*a, **k):
    return None


def _block_local(monkeypatch):
    """Ép đường local ra 1 stub → blocked, để kích hoạt hook2."""
    async def page(*a, **k):
        return {"metadata": {"title": "t"}, "markdown": "stub"}
    monkeypatch.setattr(scrape.clients, "fetch_page", page)
    monkeypatch.setattr(scrape.domains, "needs_fs", lambda u: False)
    monkeypatch.setattr(scrape.domains, "throttle", _anoop)
    monkeypatch.setattr(scrape.transform, "is_cloudflare_blocked", lambda r: False)
    monkeypatch.setattr(scrape.transform, "is_stub", lambda md, t, u: True)
    monkeypatch.setattr(scrape.transform, "is_paywall_stub", lambda md: True)  # bỏ qua FS
    monkeypatch.setattr(scrape.transform, "to_firecrawl_data",
                        lambda *a, **k: {"markdown": "stub", "metadata": {}})
    monkeypatch.setattr(scrape.transform, "markdown_of", lambda r, o: "stub")
    monkeypatch.setattr(scrape.cache, "get", lambda *a, **k: None)


def test_external_fallback_builds_data(monkeypatch):
    async def fake_ext(p, u):
        return {"markdown": "X", "metadata": {"source": "jina", "title": "T"}}
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    out = asyncio.run(scrape._external_fallback("http://x.com", "jina"))
    assert out["markdown"] == "X"
    assert out["metadata"]["source"] == "jina"


def test_external_fallback_none_when_no_provider(monkeypatch):
    out = asyncio.run(scrape._external_fallback("http://x.com", None))
    assert out is None


def test_external_fallback_none_when_ext_none(monkeypatch):
    async def fake_ext(p, u):
        return None
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    out = asyncio.run(scrape._external_fallback("http://x.com", "jina"))
    assert out is None


def test_hook1_total_failure_uses_fallback(monkeypatch):
    async def no_page(*a, **k):
        raise RuntimeError("crawl4ai down")
    async def no_fs(*a, **k):
        return None
    async def fake_ext(p, u):
        return {"markdown": "RESCUE", "metadata": {"source": "jina"}}
    monkeypatch.setattr(scrape.clients, "fetch_page", no_page)
    monkeypatch.setattr(scrape, "_via_flaresolverr", no_fs)
    monkeypatch.setattr(scrape.domains, "needs_fs", lambda u: False)
    monkeypatch.setattr(scrape.domains, "throttle", _anoop)
    monkeypatch.setattr(scrape.cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, used = asyncio.run(
        scrape.scrape("http://x.com", ["markdown"], True, fallback="jina"))
    assert data["markdown"] == "RESCUE"
    assert data["metadata"]["source"] == "jina"


def test_hook1_total_failure_no_fallback_raises(monkeypatch):
    async def no_page(*a, **k):
        raise RuntimeError("crawl4ai down")
    async def no_fs(*a, **k):
        return None
    monkeypatch.setattr(scrape.clients, "fetch_page", no_page)
    monkeypatch.setattr(scrape, "_via_flaresolverr", no_fs)
    monkeypatch.setattr(scrape.domains, "needs_fs", lambda u: False)
    monkeypatch.setattr(scrape.domains, "throttle", _anoop)
    monkeypatch.setattr(scrape.cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(scrape, "DEFAULT_FALLBACK", "")
    try:
        asyncio.run(scrape.scrape("http://x.com", ["markdown"], True))
        assert False, "phải raise"
    except RuntimeError:
        pass


def test_hook2_blocked_uses_fallback_and_no_cache(monkeypatch):
    _block_local(monkeypatch)
    put = {"n": 0}
    monkeypatch.setattr(scrape.cache, "put",
                        lambda *a, **k: put.__setitem__("n", put["n"] + 1))

    async def fake_ext(p, u):
        return {"markdown": "EXT", "metadata": {"source": "jina"}}
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, _ = asyncio.run(
        scrape.scrape("http://x.com", ["markdown"], True, fallback="jina"))
    assert data["markdown"] == "EXT"
    assert data["metadata"]["source"] == "jina"
    assert "blocked" not in data["metadata"]
    assert put["n"] == 0          # kết quả fallback KHÔNG cache


def test_hook2_no_fallback_keeps_blocked(monkeypatch):
    _block_local(monkeypatch)
    monkeypatch.setattr(scrape, "DEFAULT_FALLBACK", "")
    called = {"n": 0}

    async def fake_ext(p, u):
        called["n"] += 1
        return None
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, _ = asyncio.run(scrape.scrape("http://x.com", ["markdown"], True))
    assert data["metadata"].get("blocked") is True
    assert called["n"] == 0       # không opt-in → không gọi provider


def test_default_fallback_env_activates(monkeypatch):
    _block_local(monkeypatch)
    monkeypatch.setattr(scrape, "DEFAULT_FALLBACK", "jina")

    async def fake_ext(p, u):
        return {"markdown": "EXT", "metadata": {"source": "jina"}}
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, _ = asyncio.run(scrape.scrape("http://x.com", ["markdown"], True))  # không nêu fallback
    assert data["metadata"]["source"] == "jina"


def test_hook2_fallback_sets_partial_when_extra_formats_requested(monkeypatch):
    """Hook2: fallback trả markdown nhưng caller yêu cầu thêm html → đánh partial=True."""
    _block_local(monkeypatch)

    async def fake_ext(p, u):
        return {"markdown": "EXT", "metadata": {"source": "jina"}}
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, _ = asyncio.run(
        scrape.scrape("http://x.com", ["markdown", "html"], True, fallback="jina"))
    assert data["metadata"]["source"] == "jina"
    assert data["metadata"].get("partial") is True


def test_cf_recheck_gan_blocked_khi_van_la_challenge(monkeypatch):
    """CF re-check (fix b75c930): result vẫn là Cloudflare-challenge (không phải stub) → blocked=true."""
    async def page(*a, **k):
        return {"metadata": {"title": "t"}, "markdown": "x"}
    monkeypatch.setattr(scrape.clients, "fetch_page", page)
    monkeypatch.setattr(scrape.domains, "needs_fs", lambda u: False)
    monkeypatch.setattr(scrape.domains, "throttle", _anoop)
    monkeypatch.setattr(scrape, "_via_flaresolverr", _anoop)
    monkeypatch.setattr(scrape.cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(scrape.transform, "is_stub", lambda md, t, u: False)
    monkeypatch.setattr(scrape.transform, "is_cloudflare_blocked", lambda r: True)
    monkeypatch.setattr(scrape.transform, "to_firecrawl_data",
                        lambda *a, **k: {"markdown": "x", "metadata": {}})
    monkeypatch.setattr(scrape.transform, "markdown_of", lambda r, o: "x")
    data, _r, _ = asyncio.run(scrape.scrape("http://x.com", ["markdown"], True))
    assert data["metadata"].get("blocked") is True


def test_external_rescue_khong_bi_cf_recheck_gan_blocked(monkeypatch):
    """Regression A1: external cứu được nội dung → CF re-check KHÔNG gắn blocked oan (giữ anti-bias đúng chiều)."""
    _block_local(monkeypatch)
    monkeypatch.setattr(scrape.transform, "is_cloudflare_blocked", lambda r: True)  # result cũ vẫn CF
    monkeypatch.setattr(scrape, "_via_flaresolverr", _anoop)

    async def fake_ext(p, u):
        return {"markdown": "EXT", "metadata": {"source": "jina"}}
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, _ = asyncio.run(scrape.scrape("http://x.com", ["markdown"], True, fallback="jina"))
    assert data["metadata"]["source"] == "jina"
    assert "blocked" not in data["metadata"]   # nội dung đã cứu → không bị coi là chặn


def test_hook1_fallback_sets_partial_when_extra_formats_requested(monkeypatch):
    """Hook1 (total failure): fallback trả markdown nhưng caller yêu cầu thêm html → partial=True."""
    async def no_page(*a, **k):
        raise RuntimeError("crawl4ai down")
    async def no_fs(*a, **k):
        return None
    async def fake_ext(p, u):
        return {"markdown": "RESCUE", "metadata": {"source": "jina"}}
    monkeypatch.setattr(scrape.clients, "fetch_page", no_page)
    monkeypatch.setattr(scrape, "_via_flaresolverr", no_fs)
    monkeypatch.setattr(scrape.domains, "needs_fs", lambda u: False)
    monkeypatch.setattr(scrape.domains, "throttle", _anoop)
    monkeypatch.setattr(scrape.cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, used = asyncio.run(
        scrape.scrape("http://x.com", ["markdown", "html"], True, fallback="jina"))
    assert data["markdown"] == "RESCUE"
    assert data["metadata"].get("partial") is True
