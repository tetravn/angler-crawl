"""Trích đoạn liên quan nhất từ markdown dài, thay cho việc cắt N ký tự ĐẦU.

Vấn đề: trang thật (Gallup, báo, dashboard) có phần đầu toàn nav/menu/boilerplate; dữ liệu cần
(con số, ngày, tên) nằm sâu phía dưới. Đưa `markdown[:N]` cho LLM check/synthesize thì N ký tự đó
thường là rác điều hướng, còn sự kiện thì bị cắt mất. Helper này chọn các đoạn LIÊN QUAN nhất theo
keyword của truy vấn + mật độ dữ kiện (số, %, năm), bỏ đoạn nav, gói trong cùng budget ký tự.

Hàm thuần, không I/O, test offline được.
"""
import re

# Từ dừng + từ khung câu hỏi: loại để không khớp lan man.
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "on", "for",
    "and", "or", "what", "which", "who", "when", "where", "how", "why", "according",
    "most", "recent", "latest", "current", "national", "percentage", "number", "rate",
    "rating", "poll", "polls", "does", "did", "do", "with", "as", "by", "at", "from",
    "that", "this", "its", "their", "between", "during", "about", "into",
}

_LINK = re.compile(r"\]\(https?://")                 # cú pháp link markdown [text](http...)
_FACT = re.compile(r"\d{1,4}\s?%|\$\s?\d|\b\d{4}\b|\b\d{1,3}\b")   # số liệu: %, tiền, năm, số


# Danh từ/cụm gợi ý truy vấn cần con số (để quyết định có đáng render JS bắt số trong chart không).
_NUM_WORDS = {
    "rate", "rating", "approval", "percent", "percentage", "poll", "average", "price",
    "cost", "gdp", "population", "statistics", "figure", "figures", "score", "ratio",
    "odds", "probability", "forecast", "projection", "number", "count", "total", "amount",
    "share", "level", "salary", "revenue", "growth", "inflation", "unemployment",
}
_HAS_NUMBER = re.compile(r"\d\s?%|\b\d{2,}\b")     # % hoặc số >= 2 chữ số (bỏ số lẻ 1 chữ số nhiễu)


def wants_numbers(query: str) -> bool:
    """Truy vấn có vẻ cần dữ liệu định lượng (có chữ số, 'how many/much', hoặc danh từ số liệu)."""
    q = (query or "").lower()
    if re.search(r"\d", q):
        return True
    if "how many" in q or "how much" in q:
        return True
    toks = set(re.findall(r"[a-z]+", q))
    return bool(toks & _NUM_WORDS)


def has_numeric(text: str) -> bool:
    """True nếu text chứa con số đáng kể (%, hoặc số >= 2 chữ số)."""
    return bool(_HAS_NUMBER.search(text or ""))


def numeric_count(text: str) -> int:
    """Số lượng con số đáng kể trong text. Dùng để phân biệt 'có dữ liệu' với 'chỉ một nhãn trục'."""
    return len(_HAS_NUMBER.findall(text or ""))


def query_terms(text: str) -> list[str]:
    """Tách keyword đáng giá từ truy vấn (bỏ stopword, giữ token >= 3 ký tự)."""
    seen: list[str] = []
    for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()):
        if w not in _STOP and w not in seen:
            seen.append(w)
    return seen


def _is_boilerplate(block: str) -> bool:
    """Đoạn chủ yếu là link điều hướng / menu, ít chữ thực → bỏ."""
    links = len(_LINK.findall(block))
    words = len(re.findall(r"[A-Za-z]{2,}", block))
    if links >= 3 and words < links * 6:
        return True
    if block.count("|") >= 5 and words < 8:           # hàng menu phân cách bằng |
        return True
    return False


def _score(block: str, terms: list[str]) -> int:
    bl = block.lower()
    kw = sum(bl.count(t) for t in terms)
    facts = len(_FACT.findall(block))
    return kw * 3 + min(facts, 6)


def relevant_excerpt(markdown: str, terms: list[str], budget: int) -> str:
    """Trả đoạn liên quan nhất (<= budget ký tự), giữ thứ tự gốc. Ngắn hơn budget → trả nguyên.

    Không đoạn nào ghi điểm (truy vấn không khớp gì) → fallback về `markdown[:budget]` cũ."""
    if not markdown or len(markdown) <= budget:
        return markdown or ""
    blocks = [b.strip() for b in re.split(r"\n{2,}", markdown) if b.strip()]
    if len(blocks) <= 1:
        blocks = [b.strip() for b in markdown.split("\n") if b.strip()]
    cand = [(i, b) for i, b in enumerate(blocks) if not _is_boilerplate(b)]
    scored = sorted((( _score(b, terms), i, b) for i, b in cand), key=lambda x: -x[0])
    picked: list[tuple[int, str]] = []
    total = 0
    for s, i, b in scored:
        if s <= 0:
            break
        if total + len(b) + 2 > budget:
            continue
        picked.append((i, b))
        total += len(b) + 2
        if total >= budget:
            break
    if not picked:
        return markdown[:budget]
    picked.sort()
    return "\n\n".join(b for _, b in picked)
