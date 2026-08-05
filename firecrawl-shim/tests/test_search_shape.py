"""Test /search v1 (data phẳng) vs v2 (data={"web":[...]}) — khác shape CỐ Ý (THIET-KE-KY-THUAT.md §4.5)."""
import asyncio

from app import main
from app.models import SearchRequest

_OK = {"answered": ["bing", "duckduckgo", "google cse"], "answeredCount": 3,
       "failed": [], "degraded": False}
_DEGRADED = {"answered": ["bing"], "answeredCount": 1,
             "failed": [["brave", "too many requests"]], "degraded": True}


def _patch(monkeypatch, health):
    async def fake_do_search(body):
        return [{"url": "u1"}, {"url": "u2"}], health
    monkeypatch.setattr(main, "_do_search", fake_do_search)


def test_v1_phang_v2_boc_web(monkeypatch):
    _patch(monkeypatch, _OK)
    body = SearchRequest(query="x")
    v1 = asyncio.run(main.search_v1(body))
    v2 = asyncio.run(main.search_v2(body))
    assert isinstance(v1["data"], list) and len(v1["data"]) == 2       # v1: list phẳng
    assert isinstance(v2["data"], dict) and list(v2["data"]) == ["web"]  # v2: {"web": [...]}
    assert v2["data"]["web"] == v1["data"]


def test_khong_gan_co_khi_du_engine(monkeypatch):
    # Đủ engine → response giữ nguyên schema Firecrawl, không thêm khoá lạ.
    _patch(monkeypatch, _OK)
    v1 = asyncio.run(main.search_v1(SearchRequest(query="x")))
    assert set(v1) == {"success", "data"}


def test_gan_co_degraded_khi_thieu_engine(monkeypatch):
    # #12: caller phải biết mình đang đọc dữ liệu suy giảm, không đọc thành "không có tin".
    _patch(monkeypatch, _DEGRADED)
    for resp in (asyncio.run(main.search_v1(SearchRequest(query="x"))),
                 asyncio.run(main.search_v2(SearchRequest(query="x")))):
        assert resp["degraded"] is True
        assert "1 engine" in resp["warning"]
        assert resp["engines"] == ["bing"]
        assert resp["enginesFailed"] == [["brave", "too many requests"]]
