from app import ranking


def _mk(url, score, st="web", lang=None):
    return {"url": url, "_domain": ranking.research._domain(url),
            "_sourceType": st, "_lang": lang, "_score": score, "title": url}


def test_diversify_cap_moi_domain():
    scored = [_mk(f"https://a.com/{i}", 1.0 - i * 0.01) for i in range(6)]
    out = ranking.diversify(scored, limit=10, lam=0.7, domain_cap=2)
    from_a = [r for r in out if r["_domain"] == "a.com"]
    assert len(from_a) == 2  # cap chặn ở 2 dù còn nhiều


def test_diversify_xen_domain_khac():
    scored = (
        [_mk(f"https://a.com/{i}", 0.9 - i * 0.01) for i in range(3)]
        + [_mk("https://b.com/x", 0.5)]
    )
    out = ranking.diversify(scored, limit=4, lam=0.5, domain_cap=3)
    # với lam thấp, b.com được kéo lên sớm thay vì dồn 3 cái a.com trước
    assert out[1]["_domain"] == "b.com"


def test_diversify_ton_trong_limit():
    scored = [_mk(f"https://s{i}.com/x", 1.0 - i * 0.01) for i in range(10)]
    out = ranking.diversify(scored, limit=3, lam=0.7, domain_cap=3)
    assert len(out) == 3


def test_rank_end_to_end():
    raw = [{"url": "https://web.com/a"}, {"url": "https://arxiv.org/b"}]
    out = ranking.rank(raw, intent=None, limit=2)
    assert len(out) == 2 and all("_score" in r for r in out)
