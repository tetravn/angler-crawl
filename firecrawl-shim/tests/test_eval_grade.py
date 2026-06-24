import asyncio

from app.eval import grade


def _patch_llm(monkeypatch, *, returns=None, raises=None):
    async def fake(messages, **kw):
        _patch_llm.last_kw = kw
        if raises:
            raise raises
        return returns
    _patch_llm.last_kw = None
    monkeypatch.setattr(grade.clients, "llm_chat", fake)


def test_split_claims_basic():
    ans = "Anthropic được sáng lập năm 2021 [1]. Trụ sở ở San Francisco [2][3]. Tiêu đề"
    out = grade.split_claims(ans)
    assert len(out) == 2                       # "Tiêu đề" < 20 ký tự bị bỏ
    assert out[0]["citations"] == [1]
    assert set(out[1]["citations"]) == {2, 3}


def test_split_claims_uncited():
    out = grade.split_claims("Đây là một câu khẳng định khá dài nhưng không trích nguồn nào.")
    assert len(out) == 1
    assert out[0]["citations"] == []


def test_judge_extraction_counts(monkeypatch):
    _patch_llm(monkeypatch, returns='{"results": [{"field": "founder", "correct": true}, {"field": "year", "correct": false}]}')
    nc, nn, wrong = asyncio.run(grade.judge_extraction(
        {"founder": "X", "year": "2021"}, {"founder": "X"}))
    assert (nc, nn) == (1, 2)
    assert wrong == ["year"]
    assert _patch_llm.last_kw["model"] == grade.LLM_MODEL_SMART


def test_judge_extraction_llm_error_raises(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("LLM down"))
    try:
        asyncio.run(grade.judge_extraction({"a": "1"}, {"a": "1"}))
        assert False, "phải raise"
    except RuntimeError:
        pass


def test_judge_claim_supported(monkeypatch):
    _patch_llm(monkeypatch, returns='{"supported": true}')
    assert asyncio.run(grade.judge_claim("X founded 2021", ["... founded in 2021 ..."])) is True


def test_judge_claim_unsupported(monkeypatch):
    _patch_llm(monkeypatch, returns='{"supported": false}')
    assert asyncio.run(grade.judge_claim("X", ["unrelated"])) is False


def test_judge_claim_no_sources_false(monkeypatch):
    called = {"n": 0}

    async def fake(messages, **kw):
        called["n"] += 1
        return '{"supported": true}'
    monkeypatch.setattr(grade.clients, "llm_chat", fake)
    assert asyncio.run(grade.judge_claim("X", [])) is False
    assert called["n"] == 0                    # không gọi LLM khi không có nguồn


def test_judge_claim_llm_error_false(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("boom"))
    assert asyncio.run(grade.judge_claim("X", ["text"])) is False
