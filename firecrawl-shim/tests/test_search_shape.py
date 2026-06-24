"""Test /search v1 (data phẳng) vs v2 (data={"web":[...]}) — khác shape CỐ Ý (THIET-KE-KY-THUAT.md §4.5)."""
import asyncio

from app import main
from app.models import SearchRequest


def test_v1_phang_v2_boc_web(monkeypatch):
    async def fake_do_search(body):
        return [{"url": "u1"}, {"url": "u2"}]
    monkeypatch.setattr(main, "_do_search", fake_do_search)
    body = SearchRequest(query="x")
    v1 = asyncio.run(main.search_v1(body))
    v2 = asyncio.run(main.search_v2(body))
    assert isinstance(v1["data"], list) and len(v1["data"]) == 2       # v1: list phẳng
    assert isinstance(v2["data"], dict) and list(v2["data"]) == ["web"]  # v2: {"web": [...]}
    assert v2["data"]["web"] == v1["data"]
