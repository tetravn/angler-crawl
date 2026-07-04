"""#1 — trang lỗi interstitial Chromium (ERR_*, HTTP ERROR 4xx) không được coi là nội dung."""
import asyncio

from app import scrape, transform

# DOM đặc trưng của trang lỗi Chromium (rút gọn từ rawHtml thật của httpstat.us/404).
ERR_HTML = ('<html dir="ltr" lang="en"><head><meta charset="utf-8"></head>'
            '<body class="neterror"><div id="main-frame-error" class="interstitial-wrapper">'
            '<div id="main-message"><h1>This page isn\'t working</h1>'
            '<div class="error-code">ERR_EMPTY_RESPONSE</div></div></div></body></html>')
ERR_MD = ("#  This page isn't working\n**httpstat.us** didn't send any data.\nERR_EMPTY_RESPONSE\n"
          + "junk css leaked " * 500)


# ── unit: is_error_page ─────────────────────────────────────────────
def test_neterror_dom_la_error_page():
    assert transform.is_error_page({"html": ERR_HTML}) is True
    assert transform.is_error_page({"html": '<body class="neterror">x</body>'}) is True


def test_chrome_error_url_la_error_page():
    assert transform.is_error_page(
        {"redirected_url": "chrome-error://chromewebdata/", "html": ""}) is True


def test_bai_viet_ve_loi_KHONG_bi_oan():
    # Bài viết THẬT bàn về ERR_EMPTY_RESPONSE: markdown/html có CHỮ lỗi nhưng DOM bình thường
    # (không có id=main-frame-error / class=neterror) → không phải error page.
    real = {"html": "<html><body><article><h1>How to fix ERR_EMPTY_RESPONSE in Chrome</h1>"
                    "<p>This page isn't working? Here's what to do...</p></article></body></html>",
            "markdown": "# How to fix ERR_EMPTY_RESPONSE\nThis page isn't working? ..."}
    assert transform.is_error_page(real) is False


def test_trang_thuong_va_none():
    assert transform.is_error_page({"html": "<html><body><h1>Xin chào</h1></body></html>"}) is False
    assert transform.is_error_page(None) is False
    assert transform.is_error_page({}) is False


# ── integration: scrape() dọn nội dung + đánh dấu blocked ────────────
async def _anoop(*a, **k):
    return None


def _wire_error_page(monkeypatch):
    async def page(*a, **k):
        return {"metadata": {"title": "httpstat.us"}, "html": ERR_HTML, "markdown": ERR_MD}
    monkeypatch.setattr(scrape.clients, "fetch_page", page)
    monkeypatch.setattr(scrape, "_via_flaresolverr", _anoop)
    monkeypatch.setattr(scrape.domains, "needs_fs", lambda u: False)
    monkeypatch.setattr(scrape.domains, "throttle", _anoop)
    monkeypatch.setattr(scrape.cache, "get", lambda *a, **k: None)


def test_scrape_error_page_blocked_va_khong_phat_dom_loi(monkeypatch):
    _wire_error_page(monkeypatch)
    monkeypatch.setattr(scrape, "DEFAULT_FALLBACK", "")
    put = {"n": 0}
    monkeypatch.setattr(scrape.cache, "put", lambda *a, **k: put.__setitem__("n", put["n"] + 1))
    data, _r, _ = asyncio.run(scrape.scrape("https://httpstat.us/404", ["markdown"], True))
    assert data["metadata"].get("blocked") is True
    assert data["metadata"].get("error") == "navigation_error"
    assert data["markdown"] == ""              # KHÔNG phát DOM lỗi ~500KB
    assert put["n"] == 0                        # không cache kết quả lỗi


def test_scrape_error_page_external_fallback_cuu_duoc(monkeypatch):
    _wire_error_page(monkeypatch)

    async def fake_ext(p, u):
        return {"markdown": "NỘI DUNG THẬT", "metadata": {"source": "jina"}}
    monkeypatch.setattr(scrape.fallback_mod, "fetch_external", fake_ext)
    data, _r, _ = asyncio.run(
        scrape.scrape("https://httpstat.us/404", ["markdown"], True, fallback="jina"))
    assert data["markdown"] == "NỘI DUNG THẬT"
    assert data["metadata"]["source"] == "jina"
    assert "blocked" not in data["metadata"]
