"""Phân tích ý định truy vấn: ngôn ngữ và địa lý của các bên liên quan.

analyze_intent thử LLM (angler-fast) trước; lỗi/timeout/tắt thì về heuristic. Fail-open: ranking
không bao giờ chết vì thiếu LLM. Cache theo query để khỏi gọi lại.
"""
import logging
import re

from . import clients
from .config import LLM_MODEL_FAST, INTENT_USE_LLM, INTENT_TIMEOUT

log = logging.getLogger("shim.intent")

_CACHE: dict[str, dict] = {}

# Địa danh -> mã nước. CHỈ giữ khóa ÍT NHẬP NHẰNG: dạng tiếng Anh (match theo ranh giới từ để
# "uk" không dính "ukraine") và dạng tiếng Việt ĐA TỪ. Bỏ từ đơn tiếng Việt dễ trùng (anh/mỹ/
# đức/pháp/nga/nhật là từ thông dụng) để khỏi đoán sai geo.
_PLACES = {
    "vietnam": "vn", "viet nam": "vn", "việt nam": "vn",
    "japan": "jp", "nước nhật": "jp",
    "china": "cn", "trung quốc": "cn",
    "korea": "kr", "hàn quốc": "kr",
    "thailand": "th", "thái lan": "th",
    "france": "fr", "nước pháp": "fr",
    "germany": "de", "nước đức": "de",
    "russia": "ru", "nước nga": "ru",
    "india": "in", "ấn độ": "in",
    "britain": "gb", "anh quốc": "gb", "nước anh": "gb",
    "usa": "us", "america": "us", "nước mỹ": "us", "hoa kỳ": "us",
    "ukraine": "ua",
    "singapore": "sg", "indonesia": "id", "philippines": "ph",
    "taiwan": "tw", "đài loan": "tw",
}

# Ký tự đặc trưng tiếng Việt → đoán query là tiếng Việt.
_VI_CHARS = set("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")


def heuristic_intent(query: str) -> dict:
    """Phân tích intent bằng heuristic (không I/O)."""
    q = (query or "").lower()
    langs = ["vi", "en"] if any(c in _VI_CHARS for c in q) else ["en"]
    geos: list[str] = []
    for name, cc in _PLACES.items():
        if cc in geos:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", q):
            geos.append(cc)
    return {"languages": langs, "geos": geos, "is_global": not geos}


async def analyze_intent(query: str) -> dict:
    """Phân tích intent: thử LLM trước, rớt về heuristic nếu lỗi/timeout/tắt."""
    key = (query or "").strip().lower()
    if key in _CACHE:
        return _CACHE[key]
    intent = heuristic_intent(query)
    if INTENT_USE_LLM:
        sys = ("Analyze a search query. Return ONLY a JSON object with the languages and countries "
               "RELEVANT to the parties/topic of the query, so a search engine can cover all sides.")
        user = (f"Query: {query}\n\n"
                'Return JSON: {"languages": ["ISO-639-1"], "geos": ["ISO-3166 alpha-2 lowercase"], '
                '"is_global": true|false}. Empty geos + is_global=true if the topic is global.')
        try:
            data = await clients.llm_json(sys, user, model=LLM_MODEL_FAST, timeout=INTENT_TIMEOUT)
            langs = [str(x).lower()[:2] for x in (data.get("languages") or []) if x]
            geos = [str(x).lower()[:2] for x in (data.get("geos") or []) if x]
            if langs or geos:
                intent = {"languages": langs or intent["languages"],
                          "geos": geos, "is_global": bool(data.get("is_global", not geos))}
        except Exception as exc:
            log.info("intent LLM lỗi, dùng heuristic: %s", exc)
    _CACHE[key] = intent
    return intent
