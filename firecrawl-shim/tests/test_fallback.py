import asyncio

from app import fallback


class _Resp:
    def __init__(self, status=200, text="", json_data=None):
        self.status_code = status
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json


def _patch_http(monkeypatch, *, resp=None, raises=None, capture=None):
    class _Client:
        async def get(self, url, headers=None, follow_redirects=False):
            if capture is not None:
                capture["get"] = (url, headers)
            if raises:
                raise raises
            return resp

        async def post(self, url, json=None, headers=None):
            if capture is not None:
                capture["post"] = (url, json, headers)
            if raises:
                raise raises
            return resp

    monkeypatch.setattr(fallback.clients, "_http", lambda: _Client())


def test_jina_success(monkeypatch):
    cap = {}
    _patch_http(monkeypatch, resp=_Resp(200, "# hello"), capture=cap)
    out = asyncio.run(fallback.fetch_external("jina", "https://x.com"))
    assert out["markdown"] == "# hello"
    assert out["metadata"]["source"] == "jina"
    assert cap["get"][0].endswith("https://x.com")


def test_jina_empty_body_none(monkeypatch):
    _patch_http(monkeypatch, resp=_Resp(200, "   "))
    assert asyncio.run(fallback.fetch_external("jina", "u")) is None


def test_jina_error_status_none(monkeypatch):
    _patch_http(monkeypatch, resp=_Resp(403, "x"))
    assert asyncio.run(fallback.fetch_external("jina", "u")) is None


def test_jina_exception_none(monkeypatch):
    _patch_http(monkeypatch, raises=RuntimeError("boom"))
    assert asyncio.run(fallback.fetch_external("jina", "u")) is None


def test_firecrawl_no_key_none(monkeypatch):
    monkeypatch.setattr(fallback, "FIRECRAWL_CLOUD_API_KEY", "")
    assert asyncio.run(fallback.fetch_external("firecrawl", "u")) is None


def test_firecrawl_success(monkeypatch):
    monkeypatch.setattr(fallback, "FIRECRAWL_CLOUD_API_KEY", "k")
    _patch_http(monkeypatch, resp=_Resp(
        200, json_data={"data": {"markdown": "md", "metadata": {"title": "T"}}}))
    out = asyncio.run(fallback.fetch_external("firecrawl", "u"))
    assert out["markdown"] == "md"
    assert out["metadata"]["source"] == "firecrawl"
    assert out["metadata"]["title"] == "T"


def test_firecrawl_no_markdown_none(monkeypatch):
    monkeypatch.setattr(fallback, "FIRECRAWL_CLOUD_API_KEY", "k")
    _patch_http(monkeypatch, resp=_Resp(200, json_data={"data": {}}))
    assert asyncio.run(fallback.fetch_external("firecrawl", "u")) is None


def test_unknown_provider_none(monkeypatch):
    assert asyncio.run(fallback.fetch_external("nope", "u")) is None
