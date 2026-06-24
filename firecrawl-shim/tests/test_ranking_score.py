from app import ranking


def test_score_gan_khoa_noi_bo():
    raw = [{"url": "https://arxiv.org/abs/1", "title": "x", "engines": ["arxiv"]}]
    out = ranking.score_results(raw, None)
    r = out[0]
    assert r["_sourceType"] == "academic"
    assert r["_domain"] == "arxiv.org"
    assert set(r["_signals"]) == {
        "trust", "recency", "engine", "institutional", "global_local", "language", "geo"
    }
    assert 0.0 <= r["_score"] <= 1.0


def test_score_bo_item_khong_url():
    raw = [{"title": "no url"}, {"url": "https://a.com/x"}]
    out = ranking.score_results(raw, None)
    assert len(out) == 1 and out[0]["_domain"] == "a.com"


def test_score_academic_diem_cao_hon_web_cung_hang():
    # cùng vị trí relevance (đặt 2 list riêng để relevance như nhau ở index 0)
    aca = ranking.score_results([{"url": "https://nature.com/a"}], None)[0]
    web = ranking.score_results([{"url": "https://randomblog.com/a"}], None)[0]
    assert aca["_score"] > web["_score"]


def test_score_relevance_giam_theo_thu_tu():
    raw = [{"url": f"https://a.com/{i}"} for i in range(5)]
    out = ranking.score_results(raw, None)
    assert out[0]["_relevance"] > out[-1]["_relevance"]
