import asyncio

from app import main as main_mod, models


def test_scrape_route_passes_fallback(monkeypatch):
    cap = {}

    async def fake_scrape(url, formats, omc, *a, **kw):
        cap["fallback"] = kw.get("fallback")
        return ({"markdown": "x", "metadata": {}}, {}, False)

    async def fake_proxy(e):
        return None

    monkeypatch.setattr(main_mod.scrape_mod, "scrape", fake_scrape)
    monkeypatch.setattr(main_mod.egress_mod, "resolve_proxy", fake_proxy)
    body = models.ScrapeRequest(url="http://x.com", fallback="jina")
    out = asyncio.run(main_mod._scrape(body))
    assert out["success"] is True
    assert cap["fallback"] == "jina"


def test_scrape_route_default_fallback_none(monkeypatch):
    cap = {}

    async def fake_scrape(url, formats, omc, *a, **kw):
        cap["fallback"] = kw.get("fallback")
        return ({"markdown": "x", "metadata": {}}, {}, False)

    async def fake_proxy(e):
        return None

    monkeypatch.setattr(main_mod.scrape_mod, "scrape", fake_scrape)
    monkeypatch.setattr(main_mod.egress_mod, "resolve_proxy", fake_proxy)
    body = models.ScrapeRequest(url="http://x.com")
    asyncio.run(main_mod._scrape(body))
    assert cap["fallback"] is None
