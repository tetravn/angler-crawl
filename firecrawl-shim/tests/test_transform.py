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


# ── to_metadata: giữ đủ thẻ meta + trích ngày/tác giả (#14) ──────────────────
_LD_DATABRICKS = """
<html><head>
<meta property="article:published_time" content="Mon, 03/30/2026 - 12:43"/>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"BlogPosting",
 "datePublished":"2026-03-30T12:43:00+0000",
 "author":[{"@type":"Person","name":"Ippokratis Pandis"},
           {"@type":"Person","name":"Nikita Shamgunov"},
           {"@type":"Person","name":"Reynold Xin"}]}
</script>
</head><body>x</body></html>
"""


def test_metadata_giu_nguyen_the_og_va_article():
    # Regression #14: to_metadata từng hardcode 7 khoá rồi vứt hết og:*/article:*.
    result = {"metadata": {"title": "T", "og:image": "https://x/i.png",
                           "article:published_time": "2026-03-30T12:43:00+0000"}}
    meta = transform.to_metadata(result, "https://x/")
    assert meta["og:image"] == "https://x/i.png"
    assert meta["ogImage"] == "https://x/i.png"


def test_metadata_uu_tien_json_ld_cho_ngay_va_tac_gia():
    # Thẻ meta ghi ngày kiểu địa phương, JSON-LD ghi ISO → phải lấy ISO.
    result = {"metadata": {"article:published_time": "Mon, 03/30/2026 - 12:43",
                           "author": None},
              "html": _LD_DATABRICKS}
    meta = transform.to_metadata(result, "https://x/")
    assert meta["publishedTime"].startswith("2026-03-30T12:43:00")
    assert meta["author"] == "Ippokratis Pandis, Nikita Shamgunov, Reynold Xin"


def test_metadata_parse_duoc_the_meta_khi_khong_co_json_ld():
    result = {"metadata": {"article:published_time": "Mon, 03/30/2026 - 12:43"}}
    meta = transform.to_metadata(result, "https://x/")
    assert meta["publishedTime"] == "2026-03-30T12:43:00"


def test_metadata_khoa_luon_ton_tai_khi_trang_khong_co_ngay():
    # Phân biệt "trang không công bố ngày" với "shim chưa trích" → khoá phải có, giá trị None.
    meta = transform.to_metadata({"metadata": {"title": "T"}}, "https://x/")
    assert meta["publishedTime"] is None and meta["author"] is None
    assert "publishedTime" in meta and "author" in meta


def test_iso_date_tra_none_khi_khong_parse_duoc():
    assert transform.iso_date("hôm qua") is None
    assert transform.iso_date(None) is None


def test_pick_date_bo_qua_nguon_hong_lay_nguon_parse_duoc():
    # Regression: JSON-LD của Databricks ghi hỏng ("03/31/2026T00:00:00-08:00") còn thẻ
    # meta cùng trang lại đúng → phải lấy thẻ meta, không phải cái đứng trước.
    assert transform.pick_date("03/31/2026T00:00:00-08:00",
                               "Tue, 03/31/2026 - 17:15") == "2026-03-31T17:15:00"


def test_pick_date_giu_chuoi_goc_khi_khong_cai_nao_parse_duoc():
    assert transform.pick_date(None, "hôm qua") == "hôm qua"
    assert transform.pick_date(None, None) is None


def test_json_ld_doc_duoc_graph_va_bo_qua_json_hong():
    html = ('<script type="application/ld+json">{"@graph":[{"datePublished":"2026-01-02"}]}</script>'
            '<script type="application/ld+json">{hỏng</script>')
    assert transform.json_ld(html)["datePublished"] == "2026-01-02"
