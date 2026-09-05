"""Test chốt chặn SSRF (SDO-209).

Kiểm HAI CHIỀU: chặn đúng cái đáng chặn, và KHÔNG chặn nhầm cái hợp lệ. Chỉ kiểm một
chiều thì một hàm `return` vô điều kiện cũng "pass".

Không phụ thuộc mạng: phần phân giải tên được thay bằng monkeypatch, phần còn lại dùng
IP viết thẳng.
"""
import pytest

from app import urlguard
from app.urlguard import BlockedURL, assert_public_url, is_public_ip


# ── Phân loại IP ─────────────────────────────────────────────────────────────
# ⚠️ 100.64/10 (CGNAT, cũng là dải Tailscale) có is_private == False trên Python,
# nên nếu ai đó "đơn giản hoá" is_public_ip thành `not is_private` thì ca đó sẽ đỏ.
@pytest.mark.parametrize("addr", [
    "8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111",
])
def test_ip_cong_khai_thi_cho_qua(addr):
    assert is_public_ip(addr) is True


@pytest.mark.parametrize("addr", [
    "10.0.0.1", "172.16.0.1", "192.168.1.1",     # RFC1918
    "127.0.0.1", "::1",                            # loopback
    "169.254.169.254",                             # metadata cloud / link-local
    "100.64.0.1", "100.98.59.96",                  # CGNAT + Tailscale
    "0.0.0.0", "255.255.255.255",
    "224.0.0.1", "ff02::1",                        # multicast (is_global=True nhưng phải chặn)
    "fd00::1", "fe80::1",                          # ULA + link-local v6
    "khong-phai-ip",
])
def test_ip_khong_cong_khai_thi_chan(addr):
    assert is_public_ip(addr) is False


# ── URL ──────────────────────────────────────────────────────────────────────
def test_url_cong_khai_di_qua(monkeypatch):
    monkeypatch.setattr(urlguard, "resolve_all", lambda h: ["93.184.216.34"])
    assert_public_url("https://example.com/trang")          # không ném là đạt


def test_ip_noi_bo_viet_thang_bi_chan():
    with pytest.raises(BlockedURL):
        assert_public_url("http://10.0.0.1/")


def test_tailscale_bi_chan():
    with pytest.raises(BlockedURL, match="không công khai"):
        assert_public_url("http://100.98.59.96:17300/healthz")


def test_ten_cong_khai_nhung_tro_ve_noi_bo_bi_chan(monkeypatch):
    """Ca quan trọng nhất: chỉ so CHUỖI url thì ca này lọt."""
    monkeypatch.setattr(urlguard, "resolve_all", lambda h: ["10.1.2.3"])
    with pytest.raises(BlockedURL):
        assert_public_url("https://trong-nhu-cong-khai.example/")


def test_mot_ip_cong_khai_mot_ip_noi_bo_van_bi_chan(monkeypatch):
    """Host trả nhiều bản ghi: chỉ cần MỘT cái nội bộ là chặn, không lấy cái tốt nhất."""
    monkeypatch.setattr(urlguard, "resolve_all", lambda h: ["93.184.216.34", "192.168.0.9"])
    with pytest.raises(BlockedURL):
        assert_public_url("https://hai-mat.example/")


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://LOCALHOST/", "http://may-in.local/",
    "http://x.localhost/",
])
def test_ten_noi_bo_bi_chan_theo_ten(url):
    with pytest.raises(BlockedURL, match="nội bộ theo tên"):
        assert_public_url(url)


@pytest.mark.parametrize("url", ["ftp://a.example/", "file:///etc/passwd", "gopher://a/", "//a.example/"])
def test_scheme_la_bi_chan(url):
    with pytest.raises(BlockedURL):
        assert_public_url(url)


def test_raw_scheme_di_qua():
    """raw:// là đường nội bộ đẩy HTML đã tải vào engine, không phải fetch ra mạng."""
    assert_public_url("raw://<html></html>")


def test_khong_phan_giai_duoc_thi_chan(monkeypatch):
    monkeypatch.setattr(urlguard, "resolve_all", lambda h: [])
    with pytest.raises(BlockedURL, match="không phân giải"):
        assert_public_url("https://khong-ton-tai.example/")


# ── Lối thoát có chủ ý ───────────────────────────────────────────────────────
def test_allowlist_cho_phep_dich_noi_bo(monkeypatch):
    monkeypatch.setenv("ANGLER_ALLOW_PRIVATE_HOSTS", "noi-bo.example, khac.example")
    monkeypatch.setattr(urlguard, "resolve_all", lambda h: ["10.0.0.5"])
    assert_public_url("http://noi-bo.example/")             # không ném là đạt


def test_allowlist_khong_noi_long_cho_host_khac(monkeypatch):
    monkeypatch.setenv("ANGLER_ALLOW_PRIVATE_HOSTS", "noi-bo.example")
    monkeypatch.setattr(urlguard, "resolve_all", lambda h: ["10.0.0.5"])
    with pytest.raises(BlockedURL):
        assert_public_url("http://host-khac.example/")
