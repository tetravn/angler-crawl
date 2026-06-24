"""Firecrawl /v1/search → SearXNG (+ tùy chọn scrape nội dung mỗi kết quả).

Trả schema giống Firecrawl: list document {url, title, description, sourceType, ...}; nếu có
scrapeOptions thì mỗi item kèm thêm markdown/html/links/metadata đã scrape.

USP của Angler: /search kéo luôn nguồn khoa học (category `science` của SearXNG: arxiv, scholar,
pubmed...) và xếp hạng đa tín hiệu qua lớp ranking chung (trust × recency × engine × geo...),
kết hợp phân tích ý định query (ngôn ngữ/địa lý) để tối ưu đa dạng nguồn.
Chỉnh qua SEARCH_CATEGORIES, RANK_* trong config.
"""
import asyncio

from . import applog, clients, query_intent, ranking, scrape as scrape_mod
from .config import CRAWL_CONCURRENCY, SEARCH_CATEGORIES


async def search(
    query: str,
    *,
    limit: int = 10,
    lang: str | None = None,
    scrape_options: dict | None = None,
    proxy: str | None = None,
    categories: str | None = None,
) -> list[dict]:
    # searxng_search không nhận proxy — query egress là server-wide.
    # Lấy pool rộng hơn limit để nguồn khoa học không bị cắt TRƯỚC khi rank.
    cats = categories or SEARCH_CATEGORIES
    pool = max(limit * 3, 30) if limit else 0
    applog.event("search", "search", query=query, categories=cats, lang=lang, limit=limit)
    raw = await clients.searxng_search(query, limit=pool, lang=lang, categories=cats)
    try:
        intent = await query_intent.analyze_intent(query)
    except Exception:
        intent = None                       # fail-open: ranking vẫn chạy không intent
    ranked = ranking.rank(raw, intent, limit or len(raw))
    items: list[dict] = [
        {
            "url": r.get("url"),
            "title": r.get("title"),
            "description": r.get("content"),
            "sourceType": r["_sourceType"],
        }
        for r in ranked
    ]

    applog.event("search", "search xong", query=query, hits=len(items))
    if not scrape_options:
        return items

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

    return list(await asyncio.gather(*[enrich(it) for it in items]))
