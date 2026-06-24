"""Test phát hiện stub (vỏ rỗng anti-bot) trong transform.is_stub."""
from app import transform


def test_stub_title_bang_ten_mien():
    # title = tên miền trần → stub
    assert transform.is_stub("Vài chữ", "example.com", "https://example.com/")


def test_stub_cum_chong_bot():
    assert transform.is_stub(
        "Please verify you are a human", None, "https://x.com/abc"
    )


def test_stub_bai_viet_path_sau_gan_trong():
    # path sâu (>=2 segment) mà gần như trống → stub
    assert transform.is_stub("ngắn", None, "https://site.com/blog/bai-viet")


def test_stub_url_1_segment_chi_co_tagline():
    # Regression: vỏ TikTok chỉ có tagline, URL 1 segment (/@user) → phải là stub.
    assert transform.is_stub(
        "TikTok - Make Your Day", "TikTok - Make Your Day",
        "https://www.tiktok.com/@wireguard",
    )


def test_khong_stub_trang_goc_ngan_hop_le():
    # example.com: trang gốc (path rỗng), nội dung ngắn nhưng hợp lệ → KHÔNG stub.
    md = ("This domain is for use in illustrative examples in documents. "
          "You may use this domain in literature without prior coordination.")
    assert not transform.is_stub(md, "Example Domain", "https://example.com/")


def test_khong_stub_path_sau_du_dai():
    md = "x" * 500
    assert not transform.is_stub(md, "Bài viết thật", "https://site.com/blog/bai")


# ── is_cloudflare_blocked ──
def test_cf_blocked_theo_status():
    assert transform.is_cloudflare_blocked({"status_code": 403})
    assert transform.is_cloudflare_blocked({"status_code": 503})
    assert not transform.is_cloudflare_blocked({"status_code": 200, "html": "<p>ok</p>"})


def test_cf_blocked_theo_title_va_none():
    assert transform.is_cloudflare_blocked({"metadata": {"title": "Just a moment..."}})
    assert transform.is_cloudflare_blocked(None)   # result rỗng = coi như chặn


# ── markdown_of: lưới an toàn 30% (key design — KHÔNG để PruningContentFilter cắt quá tay) ──
def test_markdown_of_luoi_an_toan_tra_raw_khi_cat_qua_tay():
    raw = "x" * 3000
    result = {"markdown": {"raw_markdown": raw, "fit_markdown": "y" * 200}}  # fit < 30% raw
    assert transform.markdown_of(result, True) == raw   # trả full raw, không mất nội dung


def test_markdown_of_dung_fit_khi_du_lon():
    raw = "x" * 3000
    fit = "y" * 2000   # >= 30% raw
    result = {"markdown": {"raw_markdown": raw, "fit_markdown": fit}}
    assert transform.markdown_of(result, True) == fit
