"""Rate limit theo IP client — chỉ cần khi mở Angler ra internet.

Mặc định TẮT (RATE_LIMIT_PER_MIN=0) để không đổi hành vi của bản chạy trong mạng nhà.
Bật lên khi host public: /v1/extract và /v1/deep-research tiêu key LLM thật, nên một
người lạ gọi vòng lặp là đốt hạn mức của chủ stack.

Cửa sổ trượt bằng deque timestamp. Bộ nhớ theo số IP đã gặp, không theo số request.
"""
import time
from collections import defaultdict, deque

from .config import RATE_LIMIT_PER_MIN

_WINDOW = 60.0
# ponytail: dict trong RAM, mất khi restart và không chia sẻ giữa nhiều bản shim.
# Đúng cho stack một container. Nhiều replica thì cần Redis, lúc đó thay ở đây.
_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request) -> str:
    """IP thật của client.

    Caddy NỐI THÊM ip thật vào cuối X-Forwarded-For chứ không ghi đè, nên phần tử
    CUỐI là do gateway của mình đặt. Lấy phần tử đầu thì client tự bịa header là
    né được rate limit.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "?"


def check(request, now: float | None = None) -> float | None:
    """Trả None nếu được đi tiếp, hoặc số giây phải chờ nếu đã chạm trần."""
    if RATE_LIMIT_PER_MIN <= 0:
        return None
    now = time.monotonic() if now is None else now
    q = _hits[client_ip(request)]
    while q and now - q[0] >= _WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        return _WINDOW - (now - q[0])
    q.append(now)
    return None


def reset() -> None:
    """Chỉ dùng trong test."""
    _hits.clear()
