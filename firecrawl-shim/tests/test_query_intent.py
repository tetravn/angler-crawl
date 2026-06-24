import asyncio

from app import query_intent


def test_heuristic_phat_hien_tieng_viet():
    it = query_intent.heuristic_intent("chính sách thuế Việt Nam mới nhất")
    assert "vi" in it["languages"]


def test_heuristic_mac_dinh_global_khi_khong_dia_danh():
    it = query_intent.heuristic_intent("quantum computing basics")
    assert it["is_global"] is True
    assert "en" in it["languages"]


def test_heuristic_nhan_dia_danh():
    it = query_intent.heuristic_intent("vietnam economy 2026")
    assert "vn" in it["geos"]
    assert it["is_global"] is False


def test_analyze_intent_fail_open_ve_heuristic(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(query_intent.clients, "llm_json", boom)
    monkeypatch.setattr(query_intent, "INTENT_USE_LLM", True)
    query_intent._CACHE.clear()
    it = asyncio.run(query_intent.analyze_intent("vietnam economy"))
    assert "vn" in it["geos"]            # rớt về heuristic, không raise


def test_analyze_intent_dung_llm_khi_ok(monkeypatch):
    async def fake(system, user, *, model=None, timeout=None):
        return {"languages": ["ja"], "geos": ["jp"], "is_global": False}
    monkeypatch.setattr(query_intent.clients, "llm_json", fake)
    monkeypatch.setattr(query_intent, "INTENT_USE_LLM", True)
    query_intent._CACHE.clear()
    it = asyncio.run(query_intent.analyze_intent("test query llm"))
    assert it["geos"] == ["jp"] and it["languages"] == ["ja"]


def test_heuristic_khong_false_positive_substring():
    # "ukraine" KHÔNG được đoán thành uk/gb; "duke" không thành gb; từ "anh" thông dụng không thành gb.
    assert query_intent.heuristic_intent("ukraine war 2026")["geos"] == ["ua"]
    assert "gb" not in query_intent.heuristic_intent("duke university research")["geos"]
    assert query_intent.heuristic_intent("anh yêu em nhiều lắm")["geos"] == []
    # đa từ tiếng Việt vẫn nhận đúng:
    assert "vn" in query_intent.heuristic_intent("kinh tế việt nam")["geos"]
