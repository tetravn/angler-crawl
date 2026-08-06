"""Firecrawl /v1/search → SearXNG (+ tùy chọn scrape nội dung mỗi kết quả).

Trả schema giống Firecrawl: list document {url, title, description, sourceType, ...}; nếu có
scrapeOptions thì mỗi item kèm thêm markdown/html/links/metadata đã scrape.

USP của Angler: xếp hạng đa tín hiệu qua lớp ranking chung (trust × recency × engine × geo...),
kết hợp phân tích ý định query (ngôn ngữ/địa lý) để tối ưu đa dạng nguồn.

Mặc định chỉ quét category `general`. Bản trước quét thêm `science` cho MỌI truy vấn, và đó là
nguồn chính của nhiễu học thuật ở #8 — hỏi giá ổ cứng mà kéo về arxiv/semantic scholar. Cần nguồn
khoa học thì truyền categories rõ ràng, hoặc dùng /research (nó quét đa category có chủ đích).
Chỉnh qua SEARCH_CATEGORIES, SEARCH_MIN_ENGINES, RANK_* trong config.
"""
import asyncio

from . import applog, clients, query_intent, ranking, research, scrape as scrape_mod
from .config import CRAWL_CONCURRENCY, SEARCH_CATEGORIES


async def search(
    query: str,
    *,
    limit: int = 10,
    lang: str | None = None,
    scrape_options: dict | None = None,
    proxy: str | None = None,
    categories: str | None = None,
) -> tuple[list[dict], dict]:
    """Trả (items, health) — health là sức khoẻ engine của chính lần gọi này, để caller
    gắn cờ `degraded` vào response thay vì trả kết quả suy giảm trong im lặng."""
    # searxng_search không nhận proxy — query egress là server-wide.
    # Lấy pool rộng hơn limit để nguồn khoa học không bị cắt TRƯỚC khi rank.
    cats = categories or SEARCH_CATEGORIES
    pool = max(limit * 3, 30) if limit else 0
    applog.event("search", "search", query=query, categories=cats, lang=lang, limit=limit)
    # #5: chạy SONG SONG searxng + intent (intent không phụ thuộc kết quả search) → tổng thời
    # gian = max(searxng, intent) thay vì tổng. intent fail-open: lỗi/timeout → None, ranking vẫn chạy.
    raw, intent = await asyncio.gather(
        clients.searxng_search_full(query, limit=pool, lang=lang, categories=cats),
        query_intent.analyze_intent(query),
        return_exceptions=True,
    )
    if isinstance(raw, BaseException):
        raise raw                           # searxng hỏng là lỗi thật của /search
    raw, health = raw
    if isinstance(intent, BaseException):
        intent = None
    raw = [r for r in raw if not research.is_gibberish(r.get("content"))]   # #6: loại spam/gibberish
    ranked = ranking.rank(raw, intent, limit or len(raw), query=query)
    items: list[dict] = [
        {
            "url": r.get("url"),
            "title": r.get("title"),
            "description": r.get("content"),
            "sourceType": r["_sourceType"],
        }
        for r in ranked
    ]

    applog.event("search", "search xong", query=query, hits=len(items),
                 engines=health["answeredCount"])
    if not scrape_options:
        return items, health

    formats = scrape_options.get("formats") or ["markdown"]
    only_main = scrape_options.get("onlyMainContent", True)
    sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

    async def enrich(item: dict) -> dict:
        async with sem:
            try:
                # Truyền proxy vào từng scrape kết quả (per-request egress).
                data, _r, _ = await scrape_mod.scrape(item["url"], formats, only_main, proxy=proxy)
                # Giữ url + sourceType; bổ sung markdown/html/links/metadata đã scrape.
                merged = {**item, **data}
                merged["url"] = item["url"]
                merged["sourceType"] = item["sourceType"]
                return merged
            except Exception:
                return item

    return list(await asyncio.gather(*[enrich(it) for it in items])), health
