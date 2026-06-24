"""Test /search dùng lớp ranking chung (ranking.rank) cho thứ tự + đa dạng."""
import asyncio

from app import search


def test_search_xep_hang_va_da_dang(monkeypatch):
    # 5 blog cùng domain xếp trên (relevance cao), arxiv xếp cuối (relevance thấp). Không có cap thì
    # 4 blog đầu chiếm hết limit=4, arxiv bị loại. Có cap (mặc định 3) thì chỉ 3 blog lọt, nhường chỗ
    # cho arxiv -> kiểm được cả cap domain lẫn việc nguồn academic surface lên.
    async def fake_searxng(query, *, limit=10, lang=None, categories=None):
        return ([{"url": f"https://blog.com/{i}", "title": f"blog{i}"} for i in range(5)]
                + [{"url": "https://arxiv.org/x", "title": "paper"}])
    async def fake_intent(q):
        return {"languages": ["en"], "geos": [], "is_global": True}
    monkeypatch.setattr(search.clients, "searxng_search", fake_searxng)
    monkeypatch.setattr(search.query_intent, "analyze_intent", fake_intent)
    out = asyncio.run(search.search("test", limit=4))
    assert any(x["sourceType"] == "academic" for x in out)            # arxiv lọt nhờ cap domain
    assert sum(1 for x in out if "blog.com" in x["url"]) <= 3         # cap thực sự bị kích hoạt
    assert all("sourceType" in x for x in out)


def test_search_fail_open_intent(monkeypatch):
    async def fake_searxng(query, *, limit=10, lang=None, categories=None):
        return [{"url": "https://a.com/x", "title": "x"}]
    async def boom(q):
        raise RuntimeError("intent down")
    monkeypatch.setattr(search.clients, "searxng_search", fake_searxng)
    monkeypatch.setattr(search.query_intent, "analyze_intent", boom)
    out = asyncio.run(search.search("test", limit=3))
    assert len(out) == 1 and out[0]["url"] == "https://a.com/x"
    assert "sourceType" in out[0]          # ranking vẫn gán sourceType dù intent lỗi
