"""Trạng thái theo-domain để bảo vệ IP & tiết kiệm:

1. `needs_fs`/`mark_fs`: nhớ domain vừa phải dùng FlareSolverr (CF/anti-bot) để lần
   sau đi THẲNG FlareSolverr, bỏ cú thử Crawl4AI trực tiếp chắc-chắn-thất-bại.
2. `throttle`: giãn nhịp tối thiểu giữa 2 request tới CÙNG một domain (lịch sự, đỡ bị
   rate-limit/block). Domain khác nhau không chặn lẫn nhau.

Tất cả dùng time.monotonic (không bị ảnh hưởng khi đồng hồ hệ thống nhảy) và tự hết hạn.
"""
import asyncio
import time
from urllib.parse import urlparse

from .config import FS_DOMAIN_TTL, PER_DOMAIN_DELAY_MS

# domain -> thời điểm (monotonic) hết hạn ghi-nhớ "cần FlareSolverr".
_fs_until: dict[str, float] = {}

# domain -> thời điểm (monotonic) sớm nhất được phép request tiếp.
_next_allowed: dict[str, float] = {}
_lock = asyncio.Lock()


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def needs_fs(url: str) -> bool:
    """True nếu domain này gần đây cần FlareSolverr (chưa hết hạn)."""
    if FS_DOMAIN_TTL <= 0:
        return False
    dom = _domain(url)
    until = _fs_until.get(dom)
    if until is None:
        return False
    if until < time.monotonic():
        _fs_until.pop(dom, None)
        return False
    return True


def mark_fs(url: str) -> None:
    """Ghi nhớ domain này cần FlareSolverr (gia hạn TTL)."""
    if FS_DOMAIN_TTL > 0:
        _fs_until[_domain(url)] = time.monotonic() + FS_DOMAIN_TTL


async def throttle(url: str) -> None:
    """Chờ tới lượt cho domain của url (giãn nhịp PER_DOMAIN_DELAY_MS giữa các request)."""
    delay = PER_DOMAIN_DELAY_MS / 1000.0
    if delay <= 0:
        return
    dom = _domain(url)
    async with _lock:  # giữ ngắn: chỉ tính & đặt chỗ, KHÔNG sleep trong lock
        now = time.monotonic()
        slot = _next_allowed.get(dom, 0.0)
        wait = max(0.0, slot - now)
        _next_allowed[dom] = max(now, slot) + delay
        if len(_next_allowed) > 4096:  # prune nhẹ để không phình vô hạn
            for k in [k for k, v in _next_allowed.items() if v < now]:
                _next_allowed.pop(k, None)
    if wait:
        await asyncio.sleep(wait)
