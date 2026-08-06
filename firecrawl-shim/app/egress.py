"""P9 — Chọn egress (direct/vpn/proxy) theo request, fail-open.

resolve_proxy() KHÔNG bao giờ raise: xin vpn/proxy mà chưa cấu hình hoặc proxy không
reachable → log WARNING và trả None (đi direct). Dự án cá nhân: ưu tiên không-vỡ.
"""
import asyncio
import logging
import time
from urllib.parse import urlparse, urlunparse

import httpx

from . import applog
from .config import DEFAULT_EGRESS, RESIDENTIAL_PROXY_URL, VPN_PROXY_URL

log = logging.getLogger("shim.egress")

# Cache reachability: url -> (ok: bool, expiry_monotonic). Tránh probe mỗi request.
_REACHABLE_TTL = 30.0
# Cache kết quả HỎNG ngắn hơn nhiều. Trước đây dùng chung 30s: proxy hụt vài giây lúc
# xoay IP thì suốt 30s SAU KHI nó đã trở lại, request vẫn bị đẩy đi direct — cộng thời
# gian xoay là cửa sổ lộ IP host tới ~50s mỗi lần xoay, đúng thứ VPN sinh ra để tránh.
_UNREACHABLE_TTL = 3.0
_reach_cache: dict[str, tuple[bool, float]] = {}
# Lần cuối proxy còn sống (monotonic) — dùng để phân biệt "đang xoay IP" với "hỏng hẳn".
_last_ok: dict[str, float] = {}
# Nếu proxy vừa còn sống trong khoảng này thì coi lần hụt hiện tại là tạm thời.
_RECENT_OK_WINDOW = 300.0
# Chờ tối đa bấy nhiêu giây cho proxy quay lại trước khi chịu thua và đi direct.
# Một chu kỳ xoay của gluetun đo được ~10-20s nên 25s phủ được, mà không treo lâu
# khi VPN hỏng thật (trường hợp đó _last_ok cũ nên bỏ qua bước chờ luôn).
_ROTATION_GRACE = 25.0
_RETRY_EVERY = 3.0
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
    now = time.monotonic()
    if ok:
        _last_ok[url] = now
    _reach_cache[url] = (ok, now + (_REACHABLE_TTL if ok else _UNREACHABLE_TTL))
    return ok


async def _wait_for_proxy(url: str) -> bool:
    """Chờ proxy quay lại nếu nó VỪA còn sống — nghĩa là đang xoay IP, không phải hỏng.

    Trả True nếu proxy sống lại trong thời gian chờ. Nếu proxy đã chết lâu (hoặc chưa
    từng sống) thì không chờ chút nào: chờ trong ca đó chỉ làm mọi request treo vô ích
    rồi vẫn đi direct.
    """
    last = _last_ok.get(url)
    if last is None or (time.monotonic() - last) > _RECENT_OK_WINDOW:
        return False
    deadline = time.monotonic() + _ROTATION_GRACE
    log.info("proxy %s vừa hụt nhưng mới còn sống — chờ tối đa %.0fs", url, _ROTATION_GRACE)
    while time.monotonic() < deadline:
        await asyncio.sleep(_RETRY_EVERY)
        _reach_cache.pop(url, None)  # ép probe lại, đừng đọc cache hỏng
        if await _reachable(url):
            log.info("proxy %s đã trở lại", url)
            return True
    return False


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
        # Chờ nếu đây là cú hụt tạm thời (đang xoay IP) thay vì rơi thẳng về direct —
        # rơi về direct nghĩa là request đi bằng IP host, đúng cái đang muốn giấu.
        if not await _wait_for_proxy(url):
            log.warning("egress %s không reachable → direct (LỘ IP HOST)", mode)
            applog.event("egress", "egress không reachable → direct (lộ IP host)",
                         level=logging.WARNING, mode=mode)
            return None
    applog.event("egress", "egress", mode=mode, proxy=True)
    return url
