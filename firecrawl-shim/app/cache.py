"""Cache RAM theo TTL cho kết quả scrape.

Mục đích: nhiều request cùng (url, formats, onlyMainContent) trong khoảng TTL chỉ
hit site đích MỘT lần → giảm request lặp (đỡ bị rate-limit/block IP) + giảm độ trễ.

Key theo (url, formats đã sort, onlyMainContent). Lưu/trả `deepcopy` để caller có
lỡ mutate cũng không làm hỏng entry trong cache. Bounded bởi SCRAPE_CACHE_MAX.
"""
import time
from copy import deepcopy

from .config import SCRAPE_CACHE_TTL, SCRAPE_CACHE_MAX

# key -> (expiry_monotonic, value)
_store: dict[str, tuple[float, tuple]] = {}


def _key(url: str, formats: list[str], only_main_content: bool, proxy: str | None = None) -> str:
    # proxy nằm TRONG key: nội dung lấy qua direct/vpn/proxy có thể khác nhau (IP/geo khác)
    # → KHÔNG được tái dùng chéo egress (nếu không, egress per-request bị cache che mất).
    return f"{url}|{','.join(sorted(formats))}|{int(only_main_content)}|{proxy or ''}"


def get(url: str, formats: list[str], only_main_content: bool, proxy: str | None = None):
    """Trả value đã cache (deepcopy) hoặc None nếu miss/hết hạn/tắt."""
    if SCRAPE_CACHE_TTL <= 0:
        return None
    item = _store.get(_key(url, formats, only_main_content, proxy))
    if not item:
        return None
    expiry, value = item
    if expiry < time.monotonic():
        _store.pop(_key(url, formats, only_main_content, proxy), None)
        return None
    return deepcopy(value)


def put(url: str, formats: list[str], only_main_content: bool, value: tuple,
        proxy: str | None = None) -> None:
    """Lưu value (deepcopy). Prune entry hết hạn / cũ nhất khi đầy."""
    if SCRAPE_CACHE_TTL <= 0:
        return
    if len(_store) >= SCRAPE_CACHE_MAX:
        now = time.monotonic()
        for k in [k for k, (exp, _) in _store.items() if exp < now]:
            _store.pop(k, None)
        if len(_store) >= SCRAPE_CACHE_MAX:  # vẫn đầy → bỏ entry hết hạn sớm nhất
            oldest = min(_store, key=lambda k: _store[k][0])
            _store.pop(oldest, None)
    _store[_key(url, formats, only_main_content, proxy)] = (
        time.monotonic() + SCRAPE_CACHE_TTL,
        deepcopy(value),
    )
