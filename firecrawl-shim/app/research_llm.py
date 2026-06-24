"""Phần LLM của /research (chống bias nâng cao — P5).

- translate_queries(): dịch query sang từng ngôn ngữ để search THẬT sự đa ngôn ngữ (#8).
- cross_check(): so chéo nội dung các nguồn → đồng thuận / bất đồng / lệch, gắn URL (#9).

Tất cả FAIL-OPEN: LLM thiếu/lỗi → trả fallback + chuỗi warning (không làm vỡ /research).
"""
import logging
from collections import OrderedDict

from . import clients
from .config import (
    LLM_MODEL_FAST,
    LLM_MODEL_SMART,
    LLM_HTTP_TIMEOUT,
    CROSS_CHECK_MAX,
    CROSS_CHECK_CHARS,
)

log = logging.getLogger("shim.research_llm")


async def translate_queries(
    query: str, languages: list[str | None]
) -> tuple[dict, str | None]:
    """Dịch `query` sang từng ngôn ngữ trong `languages` (#8) để search đa ngôn ngữ THẬT.

    Trả (query_by_lang, warning). query_by_lang ánh xạ MỖI phần tử languages → query sẽ dùng:
    None → query gốc; lang → bản dịch (thiếu/rỗng → query gốc).
    FAIL-OPEN: LLM lỗi/parse hỏng → toàn query gốc + warning."""
    result = {l: query for l in languages}
    targets = [l for l in languages if l]
    if not targets:
        return result, None
    sys = ("You translate a web-search query into target languages, preserving search "
           "intent. Return ONLY a JSON object mapping each language code to the translated query.")
    user = (f"Query: {query}\nLanguage codes: {', '.join(targets)}\n"
            'Return JSON like {"vi": "...", "en": "..."} for exactly those codes.')
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_FAST, timeout=LLM_HTTP_TIMEOUT)
    except Exception as exc:
        return result, f"translate_queries: {exc} — dùng query gốc cho mọi ngôn ngữ"
    for l in targets:
        t = data.get(l)
        if isinstance(t, str) and t.strip():
            result[l] = t.strip()
    return result, None


def _select_for_cross_check(
    items: list[dict], max_sources: int
) -> tuple[list[dict], int]:
    """Chọn nguồn CÓ nội dung, cân bằng theo sourceType, tối đa max_sources.

    Trả (selected, n_with_content). Cân bằng = round-robin qua các sourceType để
    không loại nào áp đảo phần đưa vào LLM."""
    have = [i for i in items
            if (i.get("markdown") or "").strip() and not i.get("blocked")]
    buckets: OrderedDict[str, list] = OrderedDict()
    for it in have:
        buckets.setdefault(it.get("sourceType", "web"), []).append(it)
    out: list[dict] = []
    while len(out) < max_sources and any(buckets.values()):
        for b in buckets.values():
            if b:
                out.append(b.pop(0))
                if len(out) >= max_sources:
                    break
    return out, len(have)


async def cross_check(
    query: str, items: list[dict], max_sources: int = CROSS_CHECK_MAX
) -> tuple[dict | None, str | None]:
    """So chéo nội dung các nguồn (#9) → JSON {consensus, disagreements, outliers}, gắn URL.

    FAIL-OPEN: không nguồn đủ nội dung / LLM lỗi → (None, warning). Cắt bớt nguồn (quá
    max_sources) → (analysis, warning thông tin) — không cắt câm."""
    selected, n_have = _select_for_cross_check(items, max_sources)
    if not selected:
        return None, "cross_check: không có nguồn nào đủ nội dung để so chéo"
    warning = None
    if n_have > len(selected):
        warning = (f"cross_check: dùng {len(selected)}/{n_have} nguồn có nội dung "
                   "(cắt bớt để vừa context)")
    blocks = []
    for n, it in enumerate(selected, 1):
        body = (it.get("markdown") or "")[:CROSS_CHECK_CHARS]
        blocks.append(f"[{n}] {it['url']} ({it.get('sourceType', 'web')})\n{body}")
    sys = ("You compare multiple sources on a topic and report where they agree and "
           "disagree. Use ONLY the URLs from the provided sources; never invent URLs. "
           "Return ONLY a JSON object.")
    user = (
        f"Topic: {query}\n\nSOURCES:\n" + "\n\n---\n\n".join(blocks) +
        '\n\nReturn JSON: {"consensus": ["shared points"], '
        '"disagreements": [{"point": "...", "positions": '
        '[{"stance": "...", "sources": ["url"]}]}], '
        '"outliers": [{"claim": "...", "source": "url"}]}'
    )
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_SMART, timeout=LLM_HTTP_TIMEOUT)
    except Exception as exc:
        return None, f"cross_check: {exc}"
    return data, warning
