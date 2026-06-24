"""P10 — Fallback nguồn ngoài (public scrape services), opt-in, fail-open.

Khi đường local (Crawl4AI + FlareSolverr) bó tay VÀ request cho phép, escalate sang một
dịch vụ public để lấy nội dung — đổi lại chia sẻ URL với bên thứ ba (nên KHÔNG bật mặc định).
Mọi provider FAIL-OPEN: chưa cấu hình / lỗi / rỗng → log WARNING + trả None (không raise).

v1: jina (free, không key) + firecrawl (cần key). Browserbase/Exa thêm sau: mỗi cái 1 hàm
_xxx(url) + 1 dòng trong PROVIDERS.
"""
import logging

from . import applog, clients
from .config import (
    JINA_BASE_URL,
    JINA_API_KEY,
    FIRECRAWL_CLOUD_URL,
    FIRECRAWL_CLOUD_API_KEY,
)

log = logging.getLogger("shim.fallback")


async def _jina(url: str) -> dict | None:
    """Jina Reader: GET r.jina.ai/<url> → markdown. Free, key tùy chọn."""
    target = f"{JINA_BASE_URL}/{url}"
    headers = {"Accept": "text/plain"}
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"
    applog.event("fallback", "fallback jina bắt đầu", url=url)
    try:
        r = await clients._http().get(target, headers=headers, follow_redirects=True)
        if r.status_code == 200 and (r.text or "").strip():
            applog.event("fallback", "fallback jina thành công", url=url)
            return {"markdown": r.text,
                    "metadata": {"source": "jina", "title": None, "statusCode": 200}}
    except Exception as exc:
        log.warning("fallback jina lỗi %s: %s", url, exc)
        applog.event("fallback", "fallback jina lỗi", level=logging.WARNING, url=url, error=str(exc))
    return None


async def _firecrawl(url: str) -> dict | None:
    """Firecrawl cloud: POST /v1/scrape → data.markdown. Cần FIRECRAWL_CLOUD_API_KEY."""
    if not FIRECRAWL_CLOUD_API_KEY:
        log.warning("fallback firecrawl chưa cấu hình FIRECRAWL_CLOUD_API_KEY → bỏ")
        applog.event("fallback", "fallback firecrawl chưa cấu hình", level=logging.WARNING, url=url)
        return None
    applog.event("fallback", "fallback firecrawl bắt đầu", url=url)
    try:
        r = await clients._http().post(
            f"{FIRECRAWL_CLOUD_URL}/v1/scrape",
            json={"url": url, "formats": ["markdown"]},
            headers={"Authorization": f"Bearer {FIRECRAWL_CLOUD_API_KEY}"})
        if r.status_code == 200:
            d = (r.json() or {}).get("data") or {}
            md = d.get("markdown")
            if md and md.strip():
                title = (d.get("metadata") or {}).get("title")
                applog.event("fallback", "fallback firecrawl thành công", url=url)
                return {"markdown": md,
                        "metadata": {"source": "firecrawl", "title": title, "statusCode": 200}}
    except Exception as exc:
        log.warning("fallback firecrawl lỗi %s: %s", url, exc)
        applog.event("fallback", "fallback firecrawl lỗi", level=logging.WARNING, url=url, error=str(exc))
    return None


PROVIDERS = {"jina": _jina, "firecrawl": _firecrawl}


async def fetch_external(provider: str, url: str) -> dict | None:
    """Gọi provider ngoài. Trả partial firecrawl data {markdown, metadata{source,...}} hoặc None.
    FAIL-OPEN: provider lạ / lỗi / rỗng → None."""
    fn = PROVIDERS.get(provider)
    if fn is None:
        log.warning("fallback provider lạ %r → bỏ", provider)
        applog.event("fallback", "fallback provider lạ", level=logging.WARNING, provider=provider, url=url)
        return None
    return await fn(url)
