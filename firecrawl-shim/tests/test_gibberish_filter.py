"""#6 — lọc kết quả spam/gibberish kiểu lorem-ipsum lọt về caller."""
import asyncio

from app import research, search

# Bằng chứng thật trong issue #6 (domain eciraipo.ar).
GIBBERISH = ("Basdif beka kamic ge ruges gojoj sof pagucufiv kugdeji cij vak apugitu "
             "dajpursub rup fozicuij zilunug wamiztos hev")


def test_gibberish_that_bi_co():
    assert research.is_gibberish(GIBBERISH) is True


def test_noi_dung_that_khong_bi_co():
    real = [
        "Best VPS hosting in Vietnam for running your own VPN server with full root access",
        "Thuê VPS giá rẻ tốc độ cao tại Việt Nam, hỗ trợ cài đặt VPN cho máy chủ riêng",
        "Comment configurer un serveur VPN sur votre VPS au Vietnam avec accès root complet",
        "Wie Sie einen eigenen VPN Server auf Ihrem VPS in Vietnam einrichten und konfigurieren",
        "Cómo configurar un servidor VPN en tu VPS de Vietnam con acceso root completo",
    ]
    for s in real:
        assert research.is_gibberish(s) is False, s


def test_snippet_ngan_khong_phan():
    # dưới ngưỡng MIN_WORDS → không đủ cơ sở, không cờ (kể cả trông lạ)
    assert research.is_gibberish("Basdif beka kamic ge") is False
    assert research.is_gibberish("") is False
    assert research.is_gibberish(None) is False


def test_khong_phan_script_phi_latin():
    # CJK/Ả Rập dài nhưng không phải Latin → bỏ qua (tránh oan nội dung thật ngôn ngữ khác)
    assert research.is_gibberish("خادم في فيتنام استضافة الخادم الافتراضي الخاص وصول كامل للجذر هنا") is False
    assert research.is_gibberish("越南 服务器 托管 虚拟 专用 服务器 完全 根 访问 权限 价格 便宜 高速") is False


def test_search_loai_gibberish(monkeypatch):
    async def fake_searxng(query, *, limit=10, lang=None, categories=None):
        return [
            {"url": "https://eciraipo.ar/x", "title": "vps", "content": GIBBERISH},
            {"url": "https://vietnix.vn/vps-vpn", "title": "Thuê VPS cài VPN",
             "content": "Thuê VPS giá rẻ tốc độ cao tại Việt Nam hỗ trợ cài đặt VPN cho máy chủ"},
        ]
    async def fake_intent(q):
        return None
    monkeypatch.setattr(search.clients, "searxng_search", fake_searxng)
    monkeypatch.setattr(search.query_intent, "analyze_intent", fake_intent)
    out = asyncio.run(search.search("VPS Việt Nam VPN", limit=5))
    urls = [x["url"] for x in out]
    assert "https://eciraipo.ar/x" not in urls           # spam bị loại
    assert "https://vietnix.vn/vps-vpn" in urls           # nguồn thật giữ lại
