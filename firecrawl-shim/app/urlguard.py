"""Chặn SSRF: không cho Angler đi lấy địa chỉ nội bộ.

VÌ SAO CẦN. Angler nhận URL từ người gọi (/v1/scrape, /v1/crawl, /v1/map) — nhưng
quan trọng hơn, `deep-research` TỰ ĐI THEO LINK tìm được trên web. Nghĩa là nội dung
web KHÔNG TIN CẬY điều khiển được địa chỉ mà Angler đi lấy. Không có bộ lọc thì một
trang bất kỳ chèn `<a href="http://192.168.1.1/">` là biến Angler thành đầu đọc mạng
nội bộ của người đang chạy nó.

CÁCH KIỂM. Phân giải tên ra IP RỒI MỚI xét, và xét MỌI bản ghi trả về — không xét
chuỗi URL. Chỉ so chuỗi thì `http://internal.example.com` (một tên công cộng trỏ về
10.0.0.1) đi lọt, và DNS-rebinding cũng đi lọt.

⚠️ QUY TẮC KHÔNG PHẢI `is_private`. Đo trên Python 3.14:

    ipaddress.ip_address("100.98.59.96").is_private   -> False   (!!)

Dải CGNAT 100.64/10 — cũng chính là dải Tailscale — KHÔNG được `is_private` coi là
riêng tư. Dựa vào `is_private` là để lọt đúng cái dải cần chặn nhất. Ngược lại
`224.0.0.1` lại có `is_global = True`. Quy tắc đúng, đã kiểm trên 18 địa chỉ IPv4 lẫn
IPv6: cho qua khi và chỉ khi `is_global and not is_multicast`.

GIỚI HẠN CÒN LẠI, nói rõ để không ai tưởng đã kín: việc tải trang do crawl4ai /
FlareSolverr thực hiện, nên nếu đích công cộng REDIRECT sang địa chỉ nội bộ thì lớp
này không thấy. Chặn được ở đây là điểm vào — phần redirect cần engine hỗ trợ.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# raw:// dùng nội bộ để đẩy HTML đã tải sẵn vào crawl4ai — không phải fetch ra mạng.
INTERNAL_SCHEMES = {"raw"}


class BlockedURL(ValueError):
    """URL bị từ chối vì trỏ tới đích không công khai."""


def _allowlist() -> set[str]:
    """Host được phép dù trỏ nội bộ. Dùng khi CỐ Ý cào một dịch vụ nội bộ.

    Đặt ANGLER_ALLOW_PRIVATE_HOSTS="host1,host2" (so khớp theo hostname, không phải IP).
    """
    raw = os.getenv("ANGLER_ALLOW_PRIVATE_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def is_public_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


def resolve_all(host: str) -> list[str]:
    """Mọi IP mà host phân giải ra (cả A lẫn AAAA). Rỗng nếu không phân giải được."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return []
    return sorted({i[4][0] for i in infos})


def assert_public_url(url: str) -> None:
    """Ném BlockedURL nếu URL trỏ tới đích không công khai. Im lặng nếu hợp lệ."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()

    if scheme in INTERNAL_SCHEMES:
        return
    if scheme not in ALLOWED_SCHEMES:
        raise BlockedURL(f"scheme không được phép: {scheme or '(trống)'} — chỉ nhận http/https")

    host = (parsed.hostname or "").lower()
    if not host:
        raise BlockedURL("URL không có hostname")
    if host in _allowlist():
        return
    # `.local` là mDNS mạng LAN; chặn theo tên vì nó thường không phân giải ở đây.
    if host.endswith(".local") or host == "localhost" or host.endswith(".localhost"):
        raise BlockedURL(f"đích nội bộ theo tên: {host}")

    # Nếu chính hostname đã là IP thì xét thẳng, khỏi phân giải.
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        addrs = resolve_all(host)
        if not addrs:
            raise BlockedURL(f"không phân giải được hostname: {host}")

    bad = [a for a in addrs if not is_public_ip(a)]
    if bad:
        raise BlockedURL(
            f"đích không công khai: {host} → {', '.join(bad)}. "
            f"Nếu CỐ Ý cào nội bộ, thêm host vào ANGLER_ALLOW_PRIVATE_HOSTS."
        )
