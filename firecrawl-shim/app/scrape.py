"""Logic scrape 1 URL (kèm CF fallback) và map 1 site. Dùng chung cho /crawl."""
import gzip
import logging
import re
from urllib.parse import urljoin, urlparse

from . import applog, cache, clients, domains, fallback as fallback_mod, transcript, transform
from .config import SITEMAP_MAX_FILES, DEFAULT_FALLBACK

log = logging.getLogger("shim.scrape")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


_SITEMAP_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)


async def _via_flaresolverr(url: str, only_main_content: bool, proxy: str | None = None) -> dict | None:
    """Giải Cloudflare bằng FlareSolverr → render HTML qua Crawl4AI (raw://)."""
    try:
        solution = (await clients.flaresolverr_get(url, proxy=proxy)).get("solution") or {}
        html = solution.get("response")
        if html:
            # raw:// không screenshot được (không có trang thật để chụp).
            result = await clients.fetch_page(
                "raw://" + html, only_main_content=only_main_content
            )
            result["status_code"] = solution.get("status") or 200
            result["url"] = url
            return result
    except Exception as exc:
        applog.event("scrape", "FlareSolverr thất bại", level=logging.WARNING, url=url, error=str(exc))
    return None


async def _scrape_video(
    url: str, formats: list[str], only_main_content: bool, proxy: str | None = None,
    bypass_cache: bool = False,
) -> tuple[dict, dict, bool]:
    """Video → transcript (caption). Trả data tương thích Firecrawl: markdown = transcript.
    Clip không caption → metadata.blocked=true (không 'tàng hình')."""
    if not bypass_cache:
        hit = cache.get(url, formats, only_main_content, proxy)
        if hit is not None:
            applog.event("cache", "cache hit (video)", level=logging.DEBUG, url=url)
            return hit
    t = await transcript.get_transcript(url, proxy=proxy)
    metadata = {
        "title": t.get("title"),
        "sourceURL": url,
        "url": url,
        "source": "caption",
        "language": t.get("language"),
    }
    if t.get("blocked"):
        metadata["blocked"] = True
        applog.event("scrape", "Video không caption (blocked)", url=url)
    data = {"markdown": t.get("text", ""), "metadata": metadata}
    out = (data, {"metadata": metadata}, False)
    if not bypass_cache and not t.get("blocked"):
        cache.put(url, formats, only_main_content, out, proxy)
    return out


async def _external_fallback(url: str, fallback: str | None) -> dict | None:
    """Gọi provider ngoài (nếu opt-in). Trả firecrawl data (đã gắn source) hoặc None. Fail-open."""
    if not fallback:
        return None
    ext = await fallback_mod.fetch_external(fallback, url)
    if not ext or not (ext.get("markdown") or "").strip():
        return None
    meta = ext.get("metadata") or {}
    source = meta.get("source")
    if not source:
        # Không có nhãn nguồn → không thể minh bạch (và sẽ lọt lưới chống-cache theo `source`).
        # Bỏ qua, coi như provider không cấp được nội dung dùng được.
        applog.event("fallback", "external thiếu metadata.source — bỏ", level=logging.WARNING, provider=fallback, url=url)
        return None
    # fetch_external trả markdown sẵn (KHÔNG phải shape Crawl4AI) → dựng data trực tiếp.
    return {
        "markdown": ext["markdown"],
        "metadata": {"source": source, "title": meta.get("title"),
                     "statusCode": 200, "url": url, "sourceURL": url},
    }


async def scrape(
    url: str,
    formats: list[str],
    only_main_content: bool,
    wait_for_ms: int = 0,
    timeout_ms: int = 0,
    headers: dict | None = None,
    proxy: str | None = None,
    bypass_cache: bool = False,
    fallback: str | None = None,
) -> tuple[dict, dict, bool]:
    """Scrape 1 URL. Trả (firecrawl_data, raw_result, used_flaresolverr).

    Thử Crawl4AI trực tiếp; nếu Cloudflare chặn HOẶC Crawl4AI lỗi hẳn (browser
    chết vì challenge) thì giải bằng FlareSolverr rồi đẩy HTML (raw://) lại vào
    Crawl4AI để sinh markdown sạch.

    Tối ưu: (1) cache RAM theo TTL; (2) nhớ domain cần FlareSolverr → đi thẳng, bỏ cú
    thử trực tiếp vô ích; (3) giãn nhịp per-domain; (4) stub do paywall/login thì gắn
    `blocked` luôn — KHỎI phí một cú FlareSolverr chắc-chắn-bất-lực.

    bypass_cache=True: bỏ qua cache RAM (dùng cho /monitor để phát hiện thay đổi thật).
    """
    eff_fb = fallback or DEFAULT_FALLBACK or None   # provider hiệu lực (opt-in)
    # Nhận diện URL video → trả transcript thay vì scrape web thông thường.
    if transcript.is_video_url(url):
        return await _scrape_video(url, formats, only_main_content, proxy, bypass_cache)
    want_shot = any(f.startswith("screenshot") for f in formats)
    # Chỉ cache request "trơn". `headers`/`waitFor` ĐỔI nội dung trả về → không cache.
    # `timeout` chỉ là trần thời gian tải (không đổi nội dung) → KHÔNG tính vào đây.
    # bypass_cache=True: /monitor luôn cần dữ liệu mới để phát hiện thay đổi thật.
    cacheable = not wait_for_ms and not headers and not bypass_cache
    if cacheable:
        hit = cache.get(url, formats, only_main_content, proxy)
        if hit is not None:
            applog.event("cache", "cache hit", level=logging.DEBUG, url=url, domain=_domain(url))
            return hit

    result: dict | None = None
    used_fs = False

    # Domain gần đây luôn cần FlareSolverr → đi thẳng, bỏ cú thử Crawl4AI vô ích.
    # (Vẫn thử trực tiếp nếu cần screenshot — raw:// không chụp được.)
    if domains.needs_fs(url) and not want_shot:
        applog.event("scrape", "domain cần FlareSolverr — bỏ thử trực tiếp", url=url, domain=_domain(url))
        solved = await _via_flaresolverr(url, only_main_content, proxy)
        if solved is not None:
            result, used_fs = solved, True

    if result is None:
        await domains.throttle(url)  # giãn nhịp per-domain để đỡ bị chặn
        try:
            result = await clients.fetch_page(
                url,
                only_main_content=only_main_content,
                screenshot=want_shot,
                wait_for_ms=wait_for_ms,
                timeout_ms=timeout_ms,
                headers=headers,
                proxy=proxy,
            )
        except Exception as exc:
            applog.event("scrape", "Crawl4AI lỗi — thử FlareSolverr", level=logging.WARNING, url=url, error=str(exc))

        if result is None or transform.is_cloudflare_blocked(result):
            if result is None:
                applog.event("scrape", "Crawl4AI không lấy được — fallback FlareSolverr", url=url)
            else:
                applog.event("scrape", "Cloudflare phát hiện — fallback FlareSolverr", url=url, domain=_domain(url))
            solved = await _via_flaresolverr(url, only_main_content, proxy)
            if solved is not None:
                result, used_fs = solved, True

    if result is None:
        ext = await _external_fallback(url, eff_fb)
        if ext is not None:
            applog.event("fallback", "external cứu được sau khi local hỏng", provider=eff_fb, url=url)
            if any(f != "markdown" for f in formats):
                ext.setdefault("metadata", {})["partial"] = True
            return ext, {}, False
        raise RuntimeError(f"Crawl4AI và FlareSolverr đều thất bại cho {url}")

    data = transform.to_firecrawl_data(result, formats, only_main_content, url)

    # Stub: 200 nhưng rỗng nội dung (chống-bot/paywall/JS-shell). Thử FlareSolverr nếu
    # chưa dùng VÀ stub không phải do paywall/login (FlareSolverr không trả phí/đăng nhập
    # hộ → cú giải CF sẽ vô ích). Vẫn stub thì gắn metadata.blocked=true để nguồn KHÔNG
    # âm thầm bị tính là "có nội dung" (đó là một dạng bias do công cụ).
    title = (result.get("metadata") or {}).get("title")
    md = transform.markdown_of(result, only_main_content)
    if transform.is_stub(md, title, url):
        if not used_fs and not transform.is_paywall_stub(md):
            applog.event("scrape", "Stub anti-bot — thử FlareSolverr", url=url)
            solved = await _via_flaresolverr(url, only_main_content, proxy)
            if solved is not None:
                result, used_fs = solved, True
                data = transform.to_firecrawl_data(result, formats, only_main_content, url)
                title = (result.get("metadata") or {}).get("title")
                md = transform.markdown_of(result, only_main_content)
        elif not used_fs:
            applog.event("scrape", "Stub paywall/login — bỏ FlareSolverr", url=url)
        if transform.is_stub(md, title, url):
            data.setdefault("metadata", {})["blocked"] = True
            applog.event("scrape", "Nguồn bị chặn (stub) sau mọi cách", level=logging.WARNING, url=url, domain=_domain(url))
            ext = await _external_fallback(url, eff_fb)
            if ext is not None:
                applog.event("fallback", "external lấy được nội dung (local đã chặn)", provider=eff_fb, url=url)
                data = ext
                if any(f != "markdown" for f in formats):
                    data.setdefault("metadata", {})["partial"] = True

    # CF re-check: nếu sau mọi cách result VẪN là trang Cloudflare-challenge → đánh dấu blocked
    # (FlareSolverr có thể trả về challenge chưa giải, dài hơn ngưỡng stub nên is_stub không bắt).
    # Bỏ qua nếu data đã đến từ fallback ngoài (có metadata.source) — nội dung đã được cứu,
    # KHÔNG gắn blocked oan (result cũ vẫn là challenge nhưng data hiện là nội dung thật).
    if not (data.get("metadata") or {}).get("source") and transform.is_cloudflare_blocked(result):
        data.setdefault("metadata", {})["blocked"] = True

    blocked = bool((data.get("metadata") or {}).get("blocked"))
    # Chỉ nhớ "domain cần FlareSolverr" khi FS thật sự RA nội dung (không còn blocked) —
    # tránh ghim domain mà ngay cả FlareSolverr cũng bó tay.
    if used_fs and not blocked:
        domains.mark_fs(url)
    # Không cache kết quả blocked để lần sau còn thử lại (đỡ "đóng băng" lỗi tạm thời).
    if cacheable and not blocked and not (data.get("metadata") or {}).get("source"):
        cache.put(url, formats, only_main_content, (data, result, used_fs), proxy)

    outcome = "blocked" if blocked else "ok"
    md_out = (data.get("markdown") or "")
    src = (data.get("metadata") or {}).get("source") or ("flaresolverr" if used_fs else "crawl4ai")
    stub = bool(transform.is_stub(md_out, (data.get("metadata") or {}).get("title"), url))
    applog.event("scrape", "scrape xong", url=url, domain=_domain(url),
                 outcome=outcome, source=src, used_fs=used_fs, markdown_len=len(md_out), stub=stub)
    return data, result, used_fs


async def _discover_sitemaps(url: str, proxy: str | None = None) -> list[str]:
    """Tìm điểm vào sitemap: robots.txt (dòng Sitemap:) + các path mặc định."""
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    found: list[str] = []
    robots = await clients.http_get_text(f"{root}/robots.txt", proxy=proxy)
    if robots:
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                found.append(line.split(":", 1)[1].strip())
    found += [f"{root}/sitemap.xml", f"{root}/sitemap_index.xml"]
    return list(dict.fromkeys(found))  # dedupe, giữ thứ tự


async def _sitemap_links(url: str, proxy: str | None = None) -> list[str]:
    """Đọc sitemap đệ quy: theo sitemapindex lồng nhau, giải nén .xml.gz."""
    to_visit = await _discover_sitemaps(url, proxy)
    visited: set[str] = set()
    urls: list[str] = []
    while to_visit and len(visited) < SITEMAP_MAX_FILES:
        sm = to_visit.pop(0)
        if sm in visited:
            continue
        visited.add(sm)
        raw = await clients.http_get_bytes(sm, proxy=proxy)
        if not raw:
            continue
        if raw[:2] == b"\x1f\x8b":  # gzip magic → .xml.gz
            try:
                raw = gzip.decompress(raw)
            except Exception:
                continue
        xml = raw.decode("utf-8", "ignore")
        locs = [m.strip() for m in _SITEMAP_LOC.findall(xml) if m.strip().startswith("http")]
        if "<sitemapindex" in xml.lower():
            to_visit.extend(locs)  # đây là index → các sitemap con
        else:
            urls.extend(locs)
    return urls


def _same_site(candidate: str, base_netloc: str, include_subdomains: bool) -> bool:
    netloc = urlparse(candidate).netloc.lower()
    base = base_netloc.lower()
    if netloc == base:
        return True
    if include_subdomains:
        root = base.split(":")[0]
        return netloc.endswith("." + root)
    return False


async def site_map(
    url: str,
    limit: int = 0,
    include_subdomains: bool = False,
    search: str | None = None,
    proxy: str | None = None,
) -> list[str]:
    """Trả danh sách URL của site: link trên trang seed + sitemap.xml."""
    _data, result, _ = await scrape(url, ["links"], only_main_content=False, proxy=proxy)
    base_netloc = urlparse(url).netloc

    candidates: list[str] = []
    for href in transform.extract_links(result):
        candidates.append(urljoin(url, href))
    candidates.extend(await _sitemap_links(url, proxy))

    seen: set[str] = set()
    out: list[str] = []
    for raw in candidates:
        clean = raw.split("#")[0]
        if not _same_site(clean, base_netloc, include_subdomains):
            continue
        if search and search.lower() not in clean.lower():
            continue
        if clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out[:limit] if limit else out
