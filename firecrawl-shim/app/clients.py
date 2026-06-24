"""HTTP wrapper gọi Crawl4AI và FlareSolverr (httpx async).

- `fetch_page`  : crawl 1 URL (hoặc "raw://<html>") → 1 result dict.
- `fetch_deep`  : deep-crawl 1 site bằng BFSDeepCrawlStrategy → list result.
- `flaresolverr_get` : giải Cloudflare challenge.
- `http_get_bytes/text` : GET phụ trợ (robots.txt, sitemap, kể cả .xml.gz).

Có graceful-degradation: nếu crawler_config bị từ chối thì retry tối thiểu.
"""
import json
import logging
import re
import httpx

log = logging.getLogger("shim.clients")

from .config import (
    CRAWL4AI_URL,
    FLARESOLVERR_URL,
    SEARXNG_URL,
    HTTP_TIMEOUT,
    FLARESOLVERR_MAX_TIMEOUT,
    CRAWL4AI_CACHE_MODE,
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_STREAM,
    LLM_JSON_NATIVE,
)
from .llm_stream import stream_chat
from . import applog, egress

_client: httpx.AsyncClient | None = None
# Cache client cho từng proxy URL, tránh tạo lại mỗi request.
_proxied: dict[str, httpx.AsyncClient] = {}
# Cache client theo timeout (giây) cho đường LLM — model local có thể chậm.
_by_timeout: dict[float, httpx.AsyncClient] = {}


def _client_with_timeout(timeout: float) -> httpx.AsyncClient:
    c = _by_timeout.get(timeout)
    if c is None:
        c = httpx.AsyncClient(timeout=timeout)
        _by_timeout[timeout] = c
    return c


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    return _client


def _client_for(proxy: str | None) -> httpx.AsyncClient:
    """Trả client phù hợp: client mặc định nếu không có proxy, hoặc client riêng theo proxy URL."""
    if not proxy:
        return _http()
    c = _proxied.get(proxy)
    if c is None:
        c = httpx.AsyncClient(timeout=HTTP_TIMEOUT, proxy=proxy)
        _proxied[proxy] = c
    return c


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
    # Đóng tất cả client proxied đã tạo.
    for c in _proxied.values():
        await c.aclose()
    _proxied.clear()
    for c in _by_timeout.values():
        await c.aclose()
    _by_timeout.clear()


def _base_params(only_main_content: bool) -> dict:
    """Param dùng chung cho scrape và deep-crawl.

    onlyMainContent CHỈ gắn PruningContentFilter (ảnh hưởng `fit_markdown`), KHÔNG
    đụng `excluded_tags`/`word_count_threshold` — vì 2 cái đó cắt cả `raw_markdown`,
    làm hỏng lưới an toàn (transform.markdown_of fallback về raw khi fit quá ngắn).
    """
    params: dict = {"cache_mode": CRAWL4AI_CACHE_MODE}
    if only_main_content:
        params["markdown_generator"] = {
            "type": "DefaultMarkdownGenerator",
            "params": {
                "content_filter": {
                    "type": "PruningContentFilter",
                    "params": {"threshold": 0.5, "threshold_type": "fixed"},
                }
            },
        }
    return params


def _build_crawl_body(
    target: str, params: dict, headers: dict | None, proxy: str | None
) -> dict:
    """Dựng body cho Crawl4AI; gắn headers/proxy_config vào browser_config nếu có."""
    body: dict = {
        "urls": [target],
        "crawler_config": {"type": "CrawlerRunConfig", "params": params},
    }
    bc_params: dict = {}
    if headers:
        bc_params["headers"] = headers
    if proxy:
        bc_params["proxy_config"] = egress.proxy_config(proxy)
    if bc_params:
        body["browser_config"] = {"type": "BrowserConfig", "params": bc_params}
    return body


async def _post_crawl(body: dict) -> list[dict]:
    r = await _http().post(f"{CRAWL4AI_URL}/crawl", json=body)
    r.raise_for_status()
    data = r.json()
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"crawl4ai trả rỗng: {str(data)[:200]}")
    return results


async def fetch_page(
    target: str,
    *,
    only_main_content: bool = True,
    screenshot: bool = False,
    wait_for_ms: int = 0,
    timeout_ms: int = 0,
    headers: dict | None = None,
    proxy: str | None = None,
) -> dict:
    """Crawl 1 URL (hoặc raw://html) → result dict đầu tiên."""
    params = _base_params(only_main_content)
    if screenshot:
        params["screenshot"] = True
    if wait_for_ms:
        params["delay_before_return_html"] = max(0, wait_for_ms) / 1000.0
    if timeout_ms:
        params["page_timeout"] = int(timeout_ms)
    if proxy:
        # Cache của Crawl4AI keyed theo URL → BYPASS khi đi qua proxy để không trả/ghi
        # nội dung của egress khác (tránh nhiễm chéo direct/vpn/proxy).
        params["cache_mode"] = "BYPASS"
    body = _build_crawl_body(target, params, headers, proxy)
    try:
        return (await _post_crawl(body))[0]
    except Exception:
        # Retry tối thiểu (bỏ params phụ) NHƯNG giữ proxy — không rò IP khi đã yêu cầu egress.
        retry: dict = {"urls": [target]}
        if proxy:
            retry["browser_config"] = {
                "type": "BrowserConfig",
                "params": {"proxy_config": egress.proxy_config(proxy)},
            }
        return (await _post_crawl(retry))[0]


async def fetch_deep(
    seed: str,
    *,
    max_depth: int,
    max_pages: int,
    include_external: bool = False,
    only_main_content: bool = True,
    proxy: str | None = None,
) -> list[dict]:
    """Deep-crawl 1 site bằng engine của Crawl4AI → list result (đã có 'depth')."""
    params = _base_params(only_main_content)
    params["deep_crawl_strategy"] = {
        "type": "BFSDeepCrawlStrategy",
        "params": {
            "max_depth": max_depth,
            "max_pages": max_pages,
            "include_external": include_external,
        },
    }
    if proxy:
        params["cache_mode"] = "BYPASS"  # tránh nhiễm chéo egress ở cache Crawl4AI
    body = _build_crawl_body(seed, params, None, proxy)
    try:
        return await _post_crawl(body)
    except Exception:
        # Deep-crawl bị từ chối → tối thiểu lấy mỗi trang seed.
        return [await fetch_page(seed, only_main_content=only_main_content, proxy=proxy)]


async def browser_step(
    url: str,
    *,
    session_id: str,
    js_code: list[str] | None = None,
    js_only: bool = False,
    wait_for_ms: int = 0,
    proxy: str | None = None,
) -> dict:
    """1 bước agent qua crawl4ai SESSION (browser sống qua nhiều call).

    js_only=False: điều hướng + tải `url` (bước đầu). js_only=True: chạy `js_code` trong session
    đang mở, KHÔNG re-nav (các bước sau). cache_mode=BYPASS để luôn lấy trạng thái mới."""
    params = _base_params(True)
    params["cache_mode"] = "BYPASS"
    params["session_id"] = session_id
    params["js_only"] = js_only
    if js_code:
        params["js_code"] = js_code
    if wait_for_ms:
        params["delay_before_return_html"] = max(0, wait_for_ms) / 1000.0
    body = _build_crawl_body(url, params, None, proxy)
    return (await _post_crawl(body))[0]


async def close_session(session_id: str) -> None:
    """Best-effort giải phóng session crawl4ai. Nuốt mọi lỗi (chỉ dọn dẹp)."""
    try:
        body = {
            "urls": ["about:blank"],
            "crawler_config": {"type": "CrawlerRunConfig",
                               "params": {"session_id": session_id, "js_only": True,
                                          "cache_mode": "BYPASS"}},
        }
        await _http().post(f"{CRAWL4AI_URL}/crawl", json=body)
    except Exception:
        pass


async def flaresolverr_get(url: str, proxy: str | None = None) -> dict:
    """Giải Cloudflare challenge qua FlareSolverr, trả nguyên response JSON."""
    body = {"cmd": "request.get", "url": url, "maxTimeout": FLARESOLVERR_MAX_TIMEOUT}
    if proxy:
        body["proxy"] = {"url": proxy}
    r = await _http().post(f"{FLARESOLVERR_URL}/v1", json=body)
    r.raise_for_status()
    return r.json()


async def searxng_search(
    query: str, *, limit: int = 10, lang: str | None = None, categories: str | None = None
) -> list[dict]:
    """Tìm kiếm qua SearXNG, trả list result thô (url, title, content)."""
    params: dict = {"q": query, "format": "json"}
    if lang:
        params["language"] = lang
    if categories:
        params["categories"] = categories
    r = await _http().get(f"{SEARXNG_URL}/search", params=params)
    r.raise_for_status()
    results = r.json().get("results") or []
    return results[:limit] if limit else results


async def llm_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0,
    json_mode: bool = True,
    timeout: float | None = None,
) -> str:
    """Gọi LLM qua LiteLLM router (OpenAI-compatible). `model` None → LLM_MODEL (vd 'angler-smart').

    Litellm route tới deployment trong model-group (local/cloud, có fallback). Lỗi/hết-quota
    đều bị raise lên (caller — vd /extract — báo job failed với thông báo rõ)."""
    if LLM_STREAM:
        return await stream_chat(messages, model=model, temperature=temperature,
                                 json_mode=json_mode, timeout=timeout)
    use_model = model or LLM_MODEL
    if not (LLM_BASE_URL and use_model):
        raise RuntimeError("LLM chưa cấu hình — đặt LLM_BASE_URL + LLM_MODEL (hoặc dùng LiteLLM)")
    body: dict = {"model": use_model, "messages": messages, "temperature": temperature}
    if json_mode and LLM_JSON_NATIVE:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    client = _client_with_timeout(timeout) if timeout else _http()
    r = await client.post(f"{LLM_BASE_URL}/chat/completions", json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    # Minh bạch: LiteLLM lộ backend thực qua header x-litellm-model-api-base (thấy local/cloud nào).
    backend = r.headers.get("x-litellm-model-api-base") or "?"
    model = data.get("model")
    log.info("LLM trả lời: group=%s → backend=%s (model=%s)", use_model, backend, model)
    applog.event("llm", "LLM trả lời", group=use_model, backend=backend, model=model)
    return data["choices"][0]["message"]["content"]


def loads_json(out: str):
    """Parse JSON từ output LLM, chịu được fence ```json``` và prose lẫn quanh.

    Thứ tự: json.loads trần (model trả JSON sạch như gpt-oss) → bóc code fence (gemma hay bọc)
    → lấy block {...} hoặc [...] đầu→cuối (model reasoning hay thêm preamble). Hết cách thì raise.
    Một deployment trong chuỗi fallback của litellm có thể trả JSON không trần; helper này để
    không vỡ parse khi router rớt sang nó. Trả dict hoặc list (caller tự kiểm kiểu)."""
    try:
        return json.loads(out)
    except Exception:
        pass
    t = out.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
        try:
            return json.loads(t)
        except Exception:
            pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = t.find(open_c), t.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
    raise ValueError("không parse được JSON từ output LLM")


async def llm_json(system: str, user: str, *, model: str | None = None,
                   timeout: float | None = None) -> dict:
    """Gọi LLM mong đợi 1 JSON object (build messages + parse). Raise nếu không phải JSON object —
    caller bọc try/except để fail-open/closed như trước. Gom boilerplate dùng ở deep-research/agent/
    research/eval (mọi nơi đều qua đúng tier ảo angler-*)."""
    out = await llm_chat([{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                         model=model, json_mode=True, timeout=timeout)
    data = loads_json(out)
    if not isinstance(data, dict):
        raise ValueError("LLM không trả JSON object")
    return data


async def llm_available() -> bool:
    """Ping nhanh xem LLM đã cấu hình + reachable chưa (cho /agent, eval). Lỗi → False."""
    try:
        await llm_chat([{"role": "user", "content": "ping"}], json_mode=False)
        return True
    except Exception:
        return False


async def http_get_bytes(url: str, proxy: str | None = None) -> bytes | None:
    """GET trả bytes (cho sitemap, kể cả .xml.gz). None nếu lỗi."""
    try:
        r = await _client_for(proxy).get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (firecrawl-shim)"},
            follow_redirects=True,
        )
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None


async def http_get_text(url: str, proxy: str | None = None) -> str | None:
    raw = await http_get_bytes(url, proxy=proxy)
    return raw.decode("utf-8", "ignore") if raw is not None else None
