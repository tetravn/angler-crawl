"""#4 — query-match gate: nguồn authority cao nhưng off-topic phải bị hạ điểm."""
from app import ranking


def test_query_match_ty_le_token():
    r = {"title": "Best VPS Vietnam for VPN hosting", "content": "vps vpn hosting guide"}
    # query token (>=3, bỏ stopword): vps, vietnam, vpn, hosting  (for = stopword)
    qm = ranking.query_match("VPS Vietnam VPN hosting", r)
    assert qm == 1.0
    # off-topic: không token nào của query xuất hiện
    assert ranking.query_match("VPS Vietnam VPN hosting",
                               {"title": "QED vacuum polarization", "content": "quantum field"}) == 0.0


def test_query_rong_hoac_toan_stopword_tra_none():
    r = {"title": "abc", "content": "def"}
    assert ranking.query_match("", r) is None
    assert ranking.query_match("the a of to", r) is None      # toàn stopword


def test_academic_offtopic_chim_duoi_web_ontopic_khi_co_query():
    # Tái hiện #4: arxiv (academic, trust=1.0, institutional=1.0) nhưng nội dung lệch query;
    # 1 trang web thường nhưng đúng chủ đề. Có query → web phải trên arxiv.
    raw = [
        {"url": "https://arxiv.org/abs/hep-th/0303040",
         "title": "QED vacuum polarization", "content": "quantum electrodynamics loop", "engines": ["arxiv"]},
        {"url": "https://someblog.com/vps-vpn",
         "title": "Best VPS Vietnam allowing VPN", "content": "vps vietnam vpn hosting"},
    ]
    q = "VPS Vietnam VPN hosting"
    scored = {r["_domain"]: r for r in ranking.score_results(raw, None, q)}
    arxiv, web = scored["arxiv.org"], scored["someblog.com"]
    assert arxiv["_querymatch"] == 0.0
    assert web["_querymatch"] >= 0.75
    assert web["_score"] > arxiv["_score"]           # off-topic academic bị gate hạ mạnh


def test_khong_query_giu_hanh_vi_cu_academic_tren_web():
    # query=None → gate tắt, academic vẫn trên web (backward compatible, giống test cũ).
    raw = [
        {"url": "https://arxiv.org/abs/1", "title": "paper", "engines": ["arxiv"]},
        {"url": "https://someblog.com/a", "title": "blog"},
    ]
    scored = {r["_domain"]: r for r in ranking.score_results(raw, None)}
    assert scored["arxiv.org"]["_querymatch"] is None
    assert scored["arxiv.org"]["_score"] > scored["someblog.com"]["_score"]
