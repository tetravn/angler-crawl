import asyncio

from app import clients


def test_browser_step_builds_session_params(monkeypatch):
    cap = {}

    async def fake_post(body):
        cap["body"] = body
        return [{"markdown": "x"}]

    monkeypatch.setattr(clients, "_post_crawl", fake_post)
    out = asyncio.run(clients.browser_step(
        "http://x", session_id="S", js_code=["a();"], js_only=True))
    p = cap["body"]["crawler_config"]["params"]
    assert p["session_id"] == "S"
    assert p["js_only"] is True
    assert p["js_code"] == ["a();"]
    assert p["cache_mode"] == "BYPASS"
    assert out["markdown"] == "x"


def test_browser_step_navigate_no_js(monkeypatch):
    cap = {}

    async def fake_post(body):
        cap["body"] = body
        return [{"markdown": "home"}]

    monkeypatch.setattr(clients, "_post_crawl", fake_post)
    asyncio.run(clients.browser_step("http://x", session_id="S", js_only=False))
    p = cap["body"]["crawler_config"]["params"]
    assert p["js_only"] is False
    assert "js_code" not in p


def test_close_session_swallows_errors(monkeypatch):
    class _Client:
        async def post(self, url, json=None):
            raise RuntimeError("down")

    monkeypatch.setattr(clients, "_http", lambda: _Client())
    asyncio.run(clients.close_session("S"))   # KHÔNG được raise
