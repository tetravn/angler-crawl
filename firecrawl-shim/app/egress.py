"""P9 — Chọn egress (direct/vpn/proxy) theo request, fail-open.

resolve_proxy() KHÔNG bao giờ raise: xin vpn/proxy mà chưa cấu hình hoặc proxy không
reachable → log WARNING và trả None (đi direct). Dự án cá nhân: ưu tiên không-vỡ.
"""
import logging
import time
from urllib.parse import urlparse, urlunparse

import httpx

from . import applog
from .config import DEFAULT_EGRESS, RESIDENTIAL_PROXY_URL, VPN_PROXY_URL

log = logging.getLogger("shim.egress")

# Cache reachability: url -> (ok: bool, expiry_monotonic). Tránh probe mỗi request.
_REACHABLE_TTL = 30.0
_reach_cache: dict[str, tuple[bool, float]] = {}
# URL nhỏ, nhanh để probe proxy (trả 204, không body).
_PROBE_URL = "http://www.gstatic.com/generate_204"


def proxy_config(url: str) -> dict:
    """Tách credential nhúng trong URL → dạng Crawl4AI/Playwright cần."""
    p = urlparse(url)
    host = p.hostname or ""
    netloc = host + (f":{p.port}" if p.port else "")
    server = urlunparse((p.scheme, netloc, "", "", "", ""))
    return {"server": server, "username": p.username, "password": p.password}


def _url_for(egress: str) -> str:
    if egress == "vpn":
        return VPN_PROXY_URL
    if egress == "proxy":
        return RESIDENTIAL_PROXY_URL
    return ""


async def _reachable(url: str) -> bool:
    """Probe proxy (cache ~30s). True nếu đi qua proxy tới _PROBE_URL ổn."""
    hit = _reach_cache.get(url)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    ok = False
    try:
        async with httpx.AsyncClient(proxy=url, timeout=5.0) as c:
            r = await c.get(_PROBE_URL)
            ok = r.status_code < 500
    except Exception as exc:
        log.warning("proxy %s không reachable: %s", url, exc)
        ok = False
    _reach_cache[url] = (ok, time.monotonic() + _REACHABLE_TTL)
    return ok


async def resolve_proxy(egress: str | None) -> str | None:
    """Trả proxy URL hoặc None (direct). Fail-open, không raise."""
    mode = (egress or DEFAULT_EGRESS or "direct").lower()
    if mode == "direct":
        return None
    if mode not in ("vpn", "proxy"):
        log.warning("egress lạ %r → direct", egress)
        return None
    url = _url_for(mode)
    if not url:
        log.warning("egress %s nhưng chưa cấu hình URL → direct", mode)
        return None
    if not await _reachable(url):
        log.warning("egress %s không reachable → direct", mode)
        applog.event("egress", "egress không reachable → direct", level=logging.WARNING, mode=mode)
        return None
    applog.event("egress", "egress", mode=mode, proxy=True)
    return url
