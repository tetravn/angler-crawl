"""Lớp xếp hạng dùng chung cho /search và /research.

Tầng 1 (point-wise): mỗi tín hiệu chuẩn hóa [0,1], gộp bằng tổng có trọng số thành score.
Tầng 2 (list-wise): MMR chọn lần lượt, phạt theo độ giống đã-chọn, cap mỗi domain.
Hàm thuần, test offline được. Xem docs/THIET-KE-RANKING.md.
"""
from datetime import datetime, timezone

from . import research
from .config import (
    RANK_W_TRUST, RANK_W_RECENCY, RANK_W_ENGINE, RANK_W_INSTITUTIONAL,
    RANK_W_GLOBAL_LOCAL, RANK_W_LANGUAGE, RANK_W_GEO,
    RANK_RELEVANCE_WEIGHT, RANK_MMR_LAMBDA, RANK_DOMAIN_CAP,
)

_TRUST = {"academic": 1.0, "official": 0.95, "reference": 0.8,
          "news": 0.6, "web": 0.55, "community": 0.45, "aggregator": 0.25}

# Domain cá nhân/blog (không phải tổ chức) → institutional thấp.
_INDIVIDUAL = ("medium.com", "substack.com", "blogspot.", "wordpress.com",
               "tumblr.com", "livejournal.com", "blogger.com")
# Hậu tố tổ chức rõ ràng.
_ORG_TLD = (".gov", ".edu", ".int", ".org", ".mil", ".ac.")
# Nhà xuất bản/tổ chức học thuật danh tiếng dùng .com/.net (không khớp _ORG_TLD).
# Các domain .org (ieee.org, acm.org, science.org...) đã được _ORG_TLD bắt nên không liệt kê ở đây.
_PRESTIGIOUS = ("nature.com", "springer.com", "elsevier.com", "wiley.com",
                "jamanetwork.com", "bmj.com", "thelancet.com", "sciencedirect.com")

# ccTLD quốc gia (2 ký tự) loại trừ các đuôi "thương mại toàn cầu".
_GLOBAL_CCTLD = {"io", "co", "tv", "me", "ai", "app", "dev"}


def trust_score(source_type: str) -> float:
    return _TRUST.get(source_type, 0.55)


def age_days(result: dict) -> int | None:
    ds = result.get("publishedDate")
    if not ds:
        return None
    try:
        dt = datetime.fromisoformat(str(ds).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return None


def recency_score(age: int | None) -> float:
    if age is None:
        return 0.6
    if age <= 30:
        return 1.0
    if age <= 180:
        return 0.85
    if age <= 365:
        return 0.7
    if age <= 1095:
        return 0.5
    return 0.35


def engine_score(n: int) -> float:
    return min(max(n, 1), 3) / 3.0


def _cc(domain: str) -> str | None:
    parts = domain.split(".")
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1] not in _GLOBAL_CCTLD:
        return parts[-1]
    return None


def institutional_score(domain: str) -> float:
    d = domain.lower()
    if any(t in d for t in _ORG_TLD):
        return 1.0
    if any(p in d for p in _PRESTIGIOUS):
        return 0.95
    if any(b in d for b in _INDIVIDUAL):
        return 0.4
    return 0.7


def global_local_score(domain: str, intent: dict | None) -> float:
    cc = _cc(domain)
    if not intent or intent.get("is_global", True):
        return 0.7 if cc else 1.0           # global intent: ưu domain toàn cầu
    geos = intent.get("geos") or []
    if cc and cc in geos:
        return 1.0                          # local intent: domain đúng nước
    return 0.6


def language_score(lang: str | None, intent: dict | None) -> float:
    langs = (intent or {}).get("languages") or []
    if not langs or not lang:
        return 0.7
    return 1.0 if lang in langs else 0.4


def geo_score(domain: str, intent: dict | None) -> float:
    geos = (intent or {}).get("geos") or []
    if not geos:
        return 0.7
    cc = _cc(domain)
    return 1.0 if (cc and cc in geos) else 0.6


_WEIGHTS = {
    "trust": RANK_W_TRUST, "recency": RANK_W_RECENCY, "engine": RANK_W_ENGINE,
    "institutional": RANK_W_INSTITUTIONAL, "global_local": RANK_W_GLOBAL_LOCAL,
    "language": RANK_W_LANGUAGE, "geo": RANK_W_GEO,
}


def _lang_of(r: dict) -> str | None:
    lg = (r.get("language") or "").split("-")[0].strip().lower()
    return lg or None


def score_results(raw: list[dict], intent: dict | None) -> list[dict]:
    """Chấm điểm point-wise. Trả bản copy kèm khóa nội bộ _score/_signals/_sourceType..."""
    n = max(len(raw), 1)
    out: list[dict] = []
    for i, r in enumerate(raw):
        url = r.get("url")
        if not url:
            continue
        dom = research._domain(url)
        st = research.classify(dom, r.get("category") or "")
        lang = _lang_of(r)
        eng = r.get("engines")
        n_eng = len(eng) if isinstance(eng, (list, tuple)) else (1 if eng else 0)
        sig = {
            "trust": trust_score(st),
            "recency": recency_score(age_days(r)),
            "engine": engine_score(n_eng),
            "institutional": institutional_score(dom),
            "global_local": global_local_score(dom, intent),
            "language": language_score(lang, intent),
            "geo": geo_score(dom, intent),
        }
        wsum = sum(_WEIGHTS.values()) or 1.0
        quality = sum(_WEIGHTS[k] * sig[k] for k in sig) / wsum
        relevance = (n - i) / n
        score = (RANK_RELEVANCE_WEIGHT * relevance + quality) / (RANK_RELEVANCE_WEIGHT + 1.0)
        item = dict(r)
        item.update(_domain=dom, _sourceType=st, _lang=lang,
                    _signals=sig, _relevance=relevance, _score=score)
        out.append(item)
    return out


def _similarity(a: dict, b: dict) -> float:
    """Độ giống giữa 2 kết quả để MMR phạt. Cao nhất khi cùng domain."""
    sim = 0.0
    if a["_domain"] == b["_domain"]:
        sim = max(sim, 1.0)
    if a["_sourceType"] == b["_sourceType"]:
        sim = max(sim, 0.4)
    if a.get("_lang") and a.get("_lang") == b.get("_lang"):
        sim = max(sim, 0.2)
    ta = (a.get("title") or "").strip().lower()
    tb = (b.get("title") or "").strip().lower()
    if ta and ta == tb:
        sim = max(sim, 0.7)
    return sim


def diversify(scored: list[dict], limit: int,
              lam: float = RANK_MMR_LAMBDA, domain_cap: int = RANK_DOMAIN_CAP) -> list[dict]:
    """MMR: chọn lần lượt, cân bằng điểm và độ khác biệt; cap mỗi domain."""
    pool = list(scored)
    selected: list[dict] = []
    dom_count: dict[str, int] = {}
    while pool and (not limit or len(selected) < limit):
        best, best_val = None, float("-inf")
        for d in pool:
            if dom_count.get(d["_domain"], 0) >= domain_cap:
                continue
            sim = max((_similarity(d, s) for s in selected), default=0.0)
            val = lam * d["_score"] - (1.0 - lam) * sim
            if val > best_val:
                best_val, best = val, d
        if best is None:                      # còn lại đều chạm cap → dừng
            break
        selected.append(best)
        pool.remove(best)
        dom_count[best["_domain"]] = dom_count.get(best["_domain"], 0) + 1
    return selected


def rank(raw: list[dict], intent: dict | None, limit: int) -> list[dict]:
    """Cổng dùng chung: chấm điểm point-wise rồi đa dạng hóa MMR."""
    return diversify(score_results(raw, intent), limit)
