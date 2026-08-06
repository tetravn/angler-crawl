"""Test đếm sức khoẻ engine của SearXNG (#12) — engine hỏng có BA trạng thái, không phải hai."""
from app import clients
from app.config import SEARCH_MIN_ENGINES


def _payload(engines_per_result, unresponsive=None):
    return {
        "results": [{"url": f"https://x/{i}", "engines": e}
                    for i, e in enumerate(engines_per_result)],
        "unresponsive_engines": unresponsive or [],
    }


def test_dem_theo_engine_thuc_su_tra_ket_qua():
    h = clients.engine_health(_payload([["bing"], ["bing", "duckduckgo"], ["google cse"]]))
    assert h["answered"] == ["bing", "duckduckgo", "google cse"]
    assert h["answeredCount"] == 3


def test_engine_im_lang_khong_bi_tinh_la_khoe():
    # mojeek/wikidata/wikipedia: bật trong config, không trả gì, KHÔNG có trong
    # unresponsive_engines. Nhìn unresponsive thì tưởng còn khoẻ — phải đếm theo kết quả.
    h = clients.engine_health(_payload([["bing"]], unresponsive=[["brave", "too many requests"]]))
    assert h["answeredCount"] == 1                      # không phải "10 engine trừ 1 con lỗi"
    assert h["failed"] == [["brave", "too many requests"]]


def test_co_degraded_bat_theo_nguong():
    few = clients.engine_health(_payload([["bing"]]))
    many = clients.engine_health(_payload([[f"e{i}"] for i in range(SEARCH_MIN_ENGINES)]))
    assert few["degraded"] is True
    assert many["degraded"] is False


def test_payload_rong_la_degraded():
    h = clients.engine_health({})
    assert h["answeredCount"] == 0 and h["degraded"] is True
