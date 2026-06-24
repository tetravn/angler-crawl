"""P3 — logic chấm eval (split câu thuần + 2 LLM-judge). FAIL-OPEN ở judge_claim."""
import json
import re

from .. import clients
from ..config import LLM_MODEL_SMART, LLM_HTTP_TIMEOUT, CROSS_CHECK_CHARS

_CITE = re.compile(r"\[(\d+)\]")


def split_claims(answer: str) -> list[dict]:
    """Tách answer thành câu (newline + . ! ?); mỗi câu {text, citations:[int]}; bỏ câu < 20 ký tự."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", answer or "")
    claims: list[dict] = []
    for p in parts:
        t = p.strip()
        if len(t) < 20:
            continue
        cites = [int(n) for n in _CITE.findall(t)]
        claims.append({"text": t, "citations": cites})
    return claims


async def judge_extraction(expected: dict, extracted: dict) -> tuple[int, int, list[str]]:
    """LLM-judge: mỗi field trong expected có được extracted thể hiện đúng không. Trả (correct, total, wrong)."""
    sys = ("You verify whether extracted data contains the expected facts (allow format "
           "differences). Return ONLY a JSON object.")
    user = ("EXPECTED facts (field: value):\n" + json.dumps(expected, ensure_ascii=False) +
            "\n\nEXTRACTED JSON:\n" + json.dumps(extracted, ensure_ascii=False) +
            '\n\nReturn JSON: {"results": [{"field": "<name>", "correct": true}]} '
            "for each expected field.")
    data = await clients.llm_json(sys, user, model=LLM_MODEL_SMART, timeout=LLM_HTTP_TIMEOUT)
    correct_map = {r.get("field"): bool(r.get("correct"))
                   for r in (data.get("results") or []) if isinstance(r, dict)}
    n_total = len(expected)
    n_correct = sum(1 for k in expected if correct_map.get(k))
    wrong = [k for k in expected if not correct_map.get(k)]
    return n_correct, n_total, wrong


async def judge_claim(claim: str, source_texts: list[str]) -> bool:
    """Adversarial: nguồn có thật sự chống lưng claim? Không nguồn / lỗi → False (không-faithful)."""
    if not source_texts:
        return False
    blocks = "\n\n---\n\n".join((t or "")[:CROSS_CHECK_CHARS] for t in source_texts)
    sys = ("You adversarially verify whether the cited sources support a claim. Default to NOT "
           "supported unless the sources clearly state it. Return ONLY a JSON object.")
    user = f'CLAIM: {claim}\n\nCITED SOURCES:\n{blocks}\n\nReturn JSON: {{"supported": true}}'
    try:
        data = await clients.llm_json(sys, user, model=LLM_MODEL_SMART, timeout=LLM_HTTP_TIMEOUT)
        return bool(data.get("supported"))
    except Exception:
        return False
