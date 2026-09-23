"""Rate limit theo IP — chỉ bật khi host public, mặc định phải trong suốt."""
import pytest
from fastapi.testclient import TestClient

from app import main, ratelimit


class _Req:
    """Đủ giống Request cho ratelimit: headers + client.host."""
    def __init__(self, xff=None, host="10.0.0.1"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("c", (), {"host": host})()


@pytest.fixture(autouse=True)
def _clean():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_tat_mac_dinh_thi_khong_chan(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_PER_MIN", 0)
    for _ in range(50):
        assert ratelimit.check(_Req(), now=0.0) is None


def test_cham_tran_thi_tra_so_giay_phai_cho(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_PER_MIN", 2)
    r = _Req()
    assert ratelimit.check(r, now=0.0) is None
    assert ratelimit.check(r, now=1.0) is None
    wait = ratelimit.check(r, now=2.0)
    assert wait is not None and 0 < wait <= 60


def test_het_cua_so_thi_cho_di_tiep(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_PER_MIN", 1)
    r = _Req()
    assert ratelimit.check(r, now=0.0) is None
    assert ratelimit.check(r, now=30.0) is not None      # còn trong cửa sổ
    assert ratelimit.check(r, now=60.1) is None          # cửa sổ đã trượt qua


def test_hai_ip_dem_rieng(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_PER_MIN", 1)
    assert ratelimit.check(_Req(host="10.0.0.1"), now=0.0) is None
    assert ratelimit.check(_Req(host="10.0.0.2"), now=0.0) is None


def test_client_khong_tu_bia_duoc_ip_qua_xff(monkeypatch):
    """Caddy NỐI THÊM ip thật vào cuối XFF. Lấy phần tử đầu thì client chỉ cần
    tự gửi X-Forwarded-For khác nhau mỗi lần là thoát rate limit hoàn toàn."""
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_PER_MIN", 1)
    # Client bịa hai IP khác nhau, nhưng gateway ghi cùng một IP thật ở cuối.
    assert ratelimit.check(_Req(xff="1.1.1.1, 203.0.113.9"), now=0.0) is None
    assert ratelimit.check(_Req(xff="2.2.2.2, 203.0.113.9"), now=0.0) is not None
    assert ratelimit.client_ip(_Req(xff="1.1.1.1, 203.0.113.9")) == "203.0.113.9"


def test_endpoint_tra_429_kem_retry_after(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_PER_MIN", 1)
    c = TestClient(main.app)
    assert c.get("/health").status_code == 200
    r = c.get("/health")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert r.json()["success"] is False
