import asyncio

from app import egress, models


def test_egress_field_defaults_none():
    assert models.ScrapeRequest(url="https://x.com").egress is None
    assert models.SearchRequest(query="x").egress is None
    assert models.CrawlRequest(url="https://x.com").egress is None
    assert models.ResearchRequest(query="x").egress is None
    assert models.TranscriptRequest(urls=["https://x.com"]).egress is None


def test_egress_field_accepts_value():
    assert models.ScrapeRequest(url="https://x.com", egress="vpn").egress == "vpn"


def test_proxy_config_parses_credentials():
    assert egress.proxy_config("http://user:pass@host:8888") == {
        "server": "http://host:8888", "username": "user", "password": "pass"}
    assert egress.proxy_config("http://gluetun:8888") == {
        "server": "http://gluetun:8888", "username": None, "password": None}


def test_resolve_direct_returns_none():
    assert asyncio.run(egress.resolve_proxy("direct")) is None
    assert asyncio.run(egress.resolve_proxy(None)) is None  # DEFAULT_EGRESS=direct


def test_resolve_vpn_unconfigured_falls_back(monkeypatch):
    monkeypatch.setattr(egress, "VPN_PROXY_URL", "")
    assert asyncio.run(egress.resolve_proxy("vpn")) is None  # WARNING + direct


def test_resolve_vpn_configured_and_reachable(monkeypatch):
    monkeypatch.setattr(egress, "VPN_PROXY_URL", "http://gluetun:8888")

    async def ok(url):
        return True
    monkeypatch.setattr(egress, "_reachable", ok)
    assert asyncio.run(egress.resolve_proxy("vpn")) == "http://gluetun:8888"


def test_resolve_vpn_unreachable_falls_back(monkeypatch):
    monkeypatch.setattr(egress, "VPN_PROXY_URL", "http://gluetun:8888")

    async def no(url):
        return False
    monkeypatch.setattr(egress, "_reachable", no)
    assert asyncio.run(egress.resolve_proxy("vpn")) is None


def test_resolve_unknown_egress_falls_back():
    assert asyncio.run(egress.resolve_proxy("banana")) is None


from app import clients


def test_build_crawl_body_injects_proxy():
    body = clients._build_crawl_body("https://x.com", {"cache_mode": "ENABLED"}, None,
                                     "http://user:pass@h:8888")
    pc = body["browser_config"]["params"]["proxy_config"]
    assert pc == {"server": "http://h:8888", "username": "user", "password": "pass"}


def test_build_crawl_body_no_proxy_no_browser_config():
    body = clients._build_crawl_body("https://x.com", {"cache_mode": "ENABLED"}, None, None)
    assert "browser_config" not in body


def test_build_crawl_body_merges_headers_and_proxy():
    body = clients._build_crawl_body("https://x.com", {}, {"X-A": "1"}, "http://h:8888")
    params = body["browser_config"]["params"]
    assert params["headers"] == {"X-A": "1"}
    assert params["proxy_config"]["server"] == "http://h:8888"


from app import transcript


def test_get_transcript_passes_proxy_to_ytdlp(monkeypatch):
    seen = {}

    async def fake_ytdlp(url, languages, proxy=None):
        seen["proxy"] = proxy
        return {"text": "hi", "language": "en", "segments": [],
                "source": "caption", "title": None, "blocked": False}

    async def fake_yt_api(url, languages, proxy=None):
        return None

    monkeypatch.setattr(transcript, "_via_ytdlp", fake_ytdlp)
    monkeypatch.setattr(transcript, "_via_youtube_api", fake_yt_api)
    asyncio.run(transcript.get_transcript("https://youtu.be/abc12345678", proxy="http://h:8888"))
    assert seen["proxy"] == "http://h:8888"


from app import search as search_mod


def test_search_passes_proxy_to_scrape(monkeypatch):
    captured = {}

    async def fake_searxng(query, *, limit=10, lang=None, categories=None):
        return [{"url": "https://x.com", "title": "x", "content": "c"}]

    async def fake_scrape(url, formats, only_main, *a, proxy=None, **k):
        captured["proxy"] = proxy
        return ({"markdown": "m"}, {}, False)

    monkeypatch.setattr(search_mod.clients, "searxng_search", fake_searxng)
    monkeypatch.setattr(search_mod.scrape_mod, "scrape", fake_scrape)
    asyncio.run(search_mod.search("q", scrape_options={"formats": ["markdown"]},
                                  proxy="http://h:8888"))
    assert captured["proxy"] == "http://h:8888"


def test_fetch_page_retry_keeps_proxy(monkeypatch):
    calls = []

    async def fake_post(body):
        calls.append(body)
        if len(calls) == 1:
            raise RuntimeError("first attempt rejected")
        return [{"ok": True}]

    monkeypatch.setattr(clients, "_post_crawl", fake_post)
    asyncio.run(clients.fetch_page("https://x.com", proxy="http://user:pass@h:8888"))
    # Lần retry (call thứ 2) vẫn phải mang proxy_config
    pc = calls[1]["browser_config"]["params"]["proxy_config"]
    assert pc["server"] == "http://h:8888"


def test_fetch_page_retry_no_proxy_stays_bare(monkeypatch):
    calls = []

    async def fake_post(body):
        calls.append(body)
        if len(calls) == 1:
            raise RuntimeError("first attempt rejected")
        return [{"ok": True}]

    monkeypatch.setattr(clients, "_post_crawl", fake_post)
    asyncio.run(clients.fetch_page("https://x.com"))
    assert calls[1] == {"urls": ["https://x.com"]}  # proxy=None → retry trần như cũ


# ─── Cache phải tách theo egress (proxy) — không nhiễm chéo direct/vpn/proxy ───
def test_cache_separates_by_proxy():
    from app import cache
    cache._store.clear()
    cache.put("https://x.com", ["markdown"], True, ("DIRECT",), None)
    cache.put("https://x.com", ["markdown"], True, ("VPN",), "http://gluetun:8888")
    assert cache.get("https://x.com", ["markdown"], True, None) == ("DIRECT",)
    assert cache.get("https://x.com", ["markdown"], True, "http://gluetun:8888") == ("VPN",)
    # direct KHÔNG được trả entry của proxy khác
    assert cache.get("https://x.com", ["markdown"], True, "http://other:9999") is None
