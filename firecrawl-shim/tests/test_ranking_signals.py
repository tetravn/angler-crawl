from app import ranking


def test_trust_score_theo_tier():
    assert ranking.trust_score("academic") == 1.0
    assert ranking.trust_score("official") > ranking.trust_score("web")
    assert ranking.trust_score("aggregator") < ranking.trust_score("web")
    assert ranking.trust_score("khong-biet") == 0.55  # default web-ish


def test_recency_score_moi_cao_hon_cu():
    assert ranking.recency_score(5) > ranking.recency_score(1000)
    assert ranking.recency_score(None) == 0.6  # thiếu ngày = trung tính
    assert 0.0 <= ranking.recency_score(5000) <= 1.0


def test_engine_score_nhieu_engine_cao_hon():
    assert ranking.engine_score(3) >= ranking.engine_score(1)
    assert ranking.engine_score(0) == ranking.engine_score(1)  # coi như 1
    assert ranking.engine_score(10) == 1.0


def test_institutional_score():
    assert ranking.institutional_score("nature.com") >= 0.9
    assert ranking.institutional_score("who.int") >= 0.9
    assert ranking.institutional_score("medium.com") <= 0.5
    assert ranking.institutional_score("example.com") == 0.7


def test_global_local_score_theo_intent():
    g = {"languages": ["en"], "geos": [], "is_global": True}
    assert ranking.global_local_score("bbc.com", g) >= ranking.global_local_score("vnexpress.vn", g)
    loc = {"languages": ["vi"], "geos": ["vn"], "is_global": False}
    assert ranking.global_local_score("vnexpress.vn", loc) >= 0.9


def test_language_score():
    it = {"languages": ["vi", "en"], "geos": [], "is_global": True}
    assert ranking.language_score("vi", it) == 1.0
    assert ranking.language_score("fr", it) < 1.0
    assert ranking.language_score(None, it) == 0.7      # không rõ = trung tính
    assert ranking.language_score("fr", None) == 0.7    # không có intent = trung tính


def test_geo_score():
    it = {"languages": ["vi"], "geos": ["vn"], "is_global": False}
    assert ranking.geo_score("vnexpress.vn", it) == 1.0
    assert ranking.geo_score("example.com", it) < 1.0
    assert ranking.geo_score("example.com", None) == 0.7


def test_age_days():
    from datetime import datetime, timedelta, timezone
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    assert ranking.age_days({"publishedDate": recent}) in (3, 2, 4)
    assert ranking.age_days({}) is None
    assert ranking.age_days({"publishedDate": "rác"}) is None
