"""Dịch result của Crawl4AI sang schema response của Firecrawl + phát hiện Cloudflare/stub."""
from urllib.parse import urlparse

# Dấu hiệu trang đang bị Cloudflare chặn / hiện challenge.
# Các marker dạng class/JS (cf-chl, challenge-platform, _cf_chl_opt…) KHÔNG phụ thuộc
# ngôn ngữ → gánh phần lớn việc. Vài cụm chữ ("just a moment"…) bị bản địa hoá nên có
# thêm biến thể đa ngôn ngữ ở dưới.
_CF_MARKERS = (
    "just a moment",
    "cf-chl",
    "cf_chl_",
    "challenge-platform",
    "checking your browser",
    "attention required! | cloudflare",
    "_cf_chl_opt",
    "cf-browser-verification",
    "enable javascript and cookies to continue",
    # Đa ngôn ngữ (bản dịch của "checking your browser" / "just a moment").
    "kiểm tra trình duyệt của bạn",          # vi
    "vérification de votre navigateur",       # fr
    "ihr browser wird überprüft",             # de
    "comprobando tu navegador",               # es
)


def is_cloudflare_blocked(result: dict | None) -> bool:
    """True nếu result trông giống bị Cloudflare chặn (cần FlareSolverr)."""
    if not result:
        return True
    status = result.get("status_code") or result.get("redirected_status_code")
    if status in (403, 429, 503):
        return True
    title = ((result.get("metadata") or {}).get("title") or "").lower()
    if "just a moment" in title or "attention required" in title:
        return True
    html = (result.get("html") or result.get("cleaned_html") or "")[:20000].lower()
    return any(m in html for m in _CF_MARKERS)


# Stub do CHỐNG-BOT / JS-shell → FlareSolverr CÓ THỂ giải (render lại trang).
_ANTIBOT_PHRASES = (
    "enable javascript",
    "please enable js",
    "are you a robot",
    "verifying you are human",
    "checking if the site connection is secure",
    "access denied",
    # Đa ngôn ngữ.
    "bật javascript",                          # vi
    "vui lòng bật javascript",                 # vi
    "veuillez activer javascript",             # fr
    "activer le javascript",                   # fr
    "êtes-vous un robot",                      # fr
    "javascript aktivieren",                   # de
    "zugriff verweigert",                      # de ("access denied")
    "habilitar javascript",                    # es
    "acceso denegado",                         # es
    "verificando que eres humano",             # es
    "ativar o javascript",                     # pt
)

# Stub do PAYWALL / LOGIN / GEO-BLOCK → FlareSolverr BẤT LỰC (không trả phí/đăng nhập
# hộ, không đổi vùng). Gặp loại này thì gắn `blocked` luôn, đừng phí một cú giải CF.
_PAYWALL_PHRASES = (
    "subscribe to continue",
    "subscribe to read",
    "create a free account to read",
    "this content is not available in your",
    "log in to continue",
    "sign in to read",
    "please sign in",
    # Đa ngôn ngữ.
    "đăng ký để đọc tiếp",                      # vi
    "vui lòng đăng nhập",                       # vi
    "đăng nhập để tiếp tục",                    # vi
    "nội dung này không khả dụng",              # vi (geo-block)
    "réservé aux abonnés",                      # fr
    "abonnez-vous pour",                        # fr
    "connectez-vous pour",                      # fr
    "nur für abonnenten",                       # de
    "bitte melden sie sich an",                 # de
    "contenido exclusivo para suscriptores",    # es
    "inicia sesión para",                       # es
    "assine para continuar",                    # pt
)

# Gộp lại để dò "có phải stub không" (bất kể nguyên nhân).
_BLOCK_PHRASES = _ANTIBOT_PHRASES + _PAYWALL_PHRASES


def is_stub(markdown: str, title: str | None, url: str) -> bool:
    """True nếu nội dung là 'stub' (200 nhưng rỗng vì site chặn ở tầng ứng dụng).

    Phân biệt với trang ngắn hợp lệ (vd example.com): stub có title = tên miền trần,
    có cụm chống-bot/paywall, hoặc cực ngắn trên một URL bài viết (path sâu).
    """
    md = (markdown or "").strip()
    netloc = urlparse(url).netloc.lower()
    bare = netloc.replace("www.", "")
    t = (title or "").strip().lower()
    if t and t in (netloc, bare):
        return True
    low = md.lower()
    if any(p in low for p in _BLOCK_PHRASES):
        return True
    path = urlparse(url).path.strip("/")
    if len(md) < 40 and path:  # URL không phải gốc mà trả gần như trống (vd vỏ chỉ có tagline)
        return True
    if len(md) < 120 and path.count("/") >= 1:  # bài viết mà gần như trống
        return True
    return False


def is_paywall_stub(markdown: str) -> bool:
    """True nếu stub là do paywall/login/geo-block → FlareSolverr KHÔNG giải được.

    Dùng để bỏ qua cú FlareSolverr chắc-chắn-vô-ích và gắn `blocked` luôn.
    """
    low = (markdown or "").lower()
    return any(p in low for p in _PAYWALL_PHRASES)


def markdown_of(result: dict, only_main_content: bool) -> str:
    md = result.get("markdown")
    if isinstance(md, str):
        return md
    md = md or {}
    raw = md.get("raw_markdown") or ""
    fit = md.get("fit_markdown") or ""
    if not only_main_content:
        return raw or fit
    # Lưới an toàn: nếu PruningContentFilter cắt quá tay (fit < 30% raw trên trang
    # có nội dung đáng kể, vd văn bản luật dài), dùng bản đầy đủ để không mất nội dung.
    if fit and not (len(raw) > 2000 and len(fit) < 0.3 * len(raw)):
        return fit
    return raw or fit


def extract_links(result: dict) -> list[str]:
    """Gom internal + external link thành list URL string (dedupe, giữ thứ tự)."""
    links = result.get("links") or {}
    out: list[str] = []
    for group in ("internal", "external"):
        for item in links.get(group) or []:
            href = item.get("href") if isinstance(item, dict) else item
            if href:
                out.append(href)
    seen: set[str] = set()
    deduped: list[str] = []
    for href in out:
        if href not in seen:
            seen.add(href)
            deduped.append(href)
    return deduped


def to_metadata(result: dict, source_url: str) -> dict:
    m = result.get("metadata") or {}
    return {
        "title": m.get("title"),
        "description": m.get("description"),
        "language": m.get("language") or m.get("lang"),
        "keywords": m.get("keywords"),
        "sourceURL": source_url,
        "url": result.get("redirected_url") or result.get("url") or source_url,
        "statusCode": result.get("status_code")
        or result.get("redirected_status_code")
        or 200,
    }


def to_firecrawl_data(
    result: dict, formats: list[str], only_main_content: bool, source_url: str
) -> dict:
    """Build object `data` đúng schema Firecrawl, chỉ kèm format được yêu cầu."""
    data: dict = {"metadata": to_metadata(result, source_url)}
    if "markdown" in formats:
        data["markdown"] = markdown_of(result, only_main_content)
    if "html" in formats:
        data["html"] = result.get("cleaned_html") or result.get("fit_html") or ""
    if "rawHtml" in formats:
        data["rawHtml"] = result.get("html") or ""
    if "links" in formats:
        data["links"] = extract_links(result)
    if any(f.startswith("screenshot") for f in formats) and result.get("screenshot"):
        data["screenshot"] = result.get("screenshot")
    return data
