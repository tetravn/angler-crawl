"""Research gatherer đa-trục — chống bias bằng cách đa dạng hóa nguồn.

Trục đa dạng:
- Loại nguồn: quét nhiều `categories` SearXNG (general/news/science/...) → báo chí,
  học thuật, bách khoa, cơ quan chính thức, cộng đồng.
- Ngôn ngữ: nhiều `languages`. Khi gọi qua /research với LLM, query được DỊCH sang từng
  ngôn ngữ trước khi search (tham số `query_by_lang` — task #8), nên thật sự gom nguồn đa
  ngôn ngữ. Không có LLM → fallback dùng query gốc cho mọi lang (như trước).
- Quan điểm: danh sách `sites` (mỗi phía một tiếng nói) qua truy vấn site:.
- Chống áp đảo: cap mỗi domain + xếp hạng đa tín hiệu rồi đa dạng hóa MMR (ranking.diversify).
- Trung thực: gắn nhãn xuất xứ (sourceType), và (tùy chọn) scrape + cờ `blocked`
  cho nguồn bị stub để không âm thầm biến mất.
"""
import asyncio
from collections import Counter
from urllib.parse import urlparse

from . import applog, clients, query_intent, ranking, scrape as scrape_mod
from .config import CRAWL_CONCURRENCY

_ACADEMIC = (
    "arxiv.org", "ncbi.nlm.nih.gov", "pubmed", "doi.org", "sciencedirect.com",
    "springer", "nature.com", "mdpi.com", "semanticscholar.org", "researchgate.net",
    "jstor.org", "ssrn.com", "biorxiv.org", "medrxiv.org", "frontiersin.org",
    "wiley.com", "tandfonline.com", "plos.org", "cell.com", "bmj.com", ".edu",
)
_REFERENCE = ("wikipedia.org", "britannica.com", "wikidata.org", "scholarpedia.org")
_COMMUNITY = (
    "reddit.com", "stackexchange.com", "stackoverflow.com", "quora.com",
    "news.ycombinator.com", "medium.com", "substack.com",
)
_OFFICIAL = (
    "europa.eu", "un.org", "who.int", "worldbank.org", "oecd.org", "imf.org",
    "nasa.gov", "cdc.gov", "nih.gov",
)
_AGGREGATOR = ("msn.com", "yahoo.com", "aol.com", "news.google.com", "flipboard.com")

# Nguồn không phải bằng chứng nghiên cứu: mạng xã hội (thường là post lẻ, không trích dẫn được),
# công cụ chat LLM, từ điển, lịch. Loại hẳn trước khi scrape ở deep-research để không tốn scrape
# budget và không làm loãng phần tổng hợp. Cố ý giữ danh sách hẹp, chỉ gồm loại rõ ràng vô giá trị.
_LOW_VALUE = (
    "facebook.com", "x.com", "twitter.com", "instagram.com", "tiktok.com",
    "threads.net", "pinterest.com", "snapchat.com",
    "chatgpt.com", "chat.openai.com", "claude.ai", "gemini.google.com",
    "dictionary.cambridge.org", "dictionary.com", "thesaurus.com", "merriam-webster.com",
    "calendar-365.com", "calendar.com", "timeanddate.com",
)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def is_low_value(url: str) -> bool:
    """True nếu URL thuộc nguồn vô giá trị làm bằng chứng (social/chat/từ điển/lịch)."""
    d = _domain(url)
    return any(j in d for j in _LOW_VALUE)


def classify(domain: str, category: str) -> str:
    """Gắn nhãn loại nguồn từ domain (ưu tiên) + category."""
    d = domain.lower()
    if d.endswith(".gov") or ".gov." in d or any(o in d for o in _OFFICIAL):
        return "official"
    if any(a in d for a in _ACADEMIC):
        return "academic"
    if any(r in d for r in _REFERENCE):
        return "reference"
    if any(c in d for c in _COMMUNITY):
        return "community"
    if any(a in d for a in _AGGREGATOR):
        return "aggregator"
    if category == "science":
        return "academic"
    if category == "news":
        return "news"
    return "web"


def stats(items: list[dict]) -> dict:
    return {
        "byType": dict(Counter(i["sourceType"] for i in items)),
        "byDomain": dict(Counter(i["domain"] for i in items)),
        "blocked": sum(1 for i in items if i.get("blocked")),
    }


async def research(
    query: str,
    *,
    categories: list[str] | None = None,
    languages: list[str] | None = None,
    sites: list[str] | None = None,
    max_per_domain: int = 2,
    limit: int = 24,
    scrape: bool = False,
    query_by_lang: dict | None = None,
    proxy: str | None = None,
) -> list[dict]:
    applog.event("research", "research", query=query)
    # Phân tích ý định truy vấn để hỗ trợ ranking và chọn ngôn ngữ. Fail-open.
    try:
        intent = await query_intent.analyze_intent(query)
    except Exception:
        intent = None

    categories = categories or ["general", "news", "science"]
    if not languages:
        # Lấy languages từ intent. Đây là lưới đỡ cho lời gọi research() trực tiếp; khi đi qua
        # endpoint /research (main.py) thì intent đã được lấy + dịch query (translate_queries) ở đó
        # rồi truyền languages + query_by_lang vào, nên nhánh này thường không chạy.
        languages = (intent or {}).get("languages") or [None]

    async def by_category(cat: str, lang: str | None):
        # #8: nếu có query_by_lang → dùng query ĐÃ DỊCH cho lang này (đa ngôn ngữ THẬT);
        # không có → query gốc (hành vi cũ). `lang` vẫn truyền làm cú hích phụ.
        q = (query_by_lang or {}).get(lang, query)
        res = await clients.searxng_search(q, limit=20, lang=lang, categories=cat)
        return [(r, cat) for r in res]

    async def by_site(dom: str):
        res = await clients.searxng_search(f"{query} site:{dom}", limit=5)
        hits = [r for r in res if dom in _domain(r.get("url", ""))]
        return [(r, "perspective") for r in hits[:1]]

    jobs = [by_category(c, l) for c in categories for l in languages]
    if sites:
        jobs += [by_site(d) for d in sites]
    gathered = await asyncio.gather(*jobs, return_exceptions=True)

    # Dedupe theo URL + cap mỗi domain.
    seen: set[str] = set()
    per_domain: Counter = Counter()
    items: list[dict] = []
    for chunk in gathered:
        if isinstance(chunk, Exception):
            continue
        for r, cat in chunk:
            url = r.get("url")
            if not url or url in seen:
                continue
            dom = _domain(url)
            if per_domain[dom] >= max_per_domain:
                continue
            seen.add(url)
            per_domain[dom] += 1
            items.append({
                "url": url,
                "title": r.get("title"),
                "description": r.get("content"),
                "domain": dom,
                "sourceType": classify(dom, cat),
                "category": cat,                          # cho ranking phân loại đúng (academic theo category)
                "publishedDate": r.get("publishedDate"),  # recency signal
                "engines": r.get("engines"),              # engine_score signal
                "language": r.get("language"),            # language signal
            })

    # Xếp hạng bằng lớp ranking chung (point-wise score + MMR diversify),
    # rồi map về schema output sạch (chỉ giữ các field public, strip field nội bộ _*).
    ordered = ranking.diversify(ranking.score_results(items, intent), limit)
    items = [{
        "url": r["url"],
        "title": r.get("title"),
        "description": r.get("description"),
        "domain": r["domain"],
        "sourceType": r["sourceType"],
    } for r in ordered]

    if scrape:
        sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

        async def fill(item: dict) -> dict:
            async with sem:
                try:
                    # Truyền proxy vào từng scrape (per-request egress).
                    # searxng_search không nhận proxy — query egress là server-wide.
                    data, _r, _ = await scrape_mod.scrape(item["url"], ["markdown"], True, proxy=proxy)
                    item["markdown"] = data.get("markdown")
                    item["blocked"] = bool((data.get("metadata") or {}).get("blocked"))
                except Exception:
                    item["blocked"] = True
            return item

        items = list(await asyncio.gather(*[fill(i) for i in items]))

    blocked_count = sum(1 for i in items if i.get("blocked"))
    applog.event("research", "research xong", query=query, sources=len(items),
                 domains=len(per_domain), blocked=blocked_count)
    return items
