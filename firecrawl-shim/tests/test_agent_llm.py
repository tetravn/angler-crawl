import asyncio

from app import agent


def _patch_llm(monkeypatch, *, returns=None, raises=None):
    async def fake(messages, **kw):
        _patch_llm.last_kw = kw
        if raises:
            raise raises
        return returns
    _patch_llm.last_kw = None
    monkeypatch.setattr(agent.clients, "llm_chat", fake)


def test_llm_available(monkeypatch):
    _patch_llm(monkeypatch, returns="hi")
    assert asyncio.run(agent._llm_available()) is True
    _patch_llm(monkeypatch, raises=RuntimeError("x"))
    assert asyncio.run(agent._llm_available()) is False


def test_plan_action_index(monkeypatch):
    _patch_llm(monkeypatch, returns='{"thought":"t","action":"click","index":4}')
    act, w = asyncio.run(agent.plan_action("goal", "obs", []))
    assert act["action"] == "click" and act["index"] == 4 and act["thought"] == "t"
    assert w is None
    assert _patch_llm.last_kw["model"] == agent.LLM_MODEL_SMART


def test_plan_action_unknown_done(monkeypatch):
    _patch_llm(monkeypatch, returns='{"action":"fly"}')
    act, w = asyncio.run(agent.plan_action("g", "o", []))
    assert act["action"] == "done"


def test_plan_action_bad_json(monkeypatch):
    _patch_llm(monkeypatch, returns="nope")
    act, w = asyncio.run(agent.plan_action("g", "o", []))
    assert act["action"] == "done" and w and "plan_action" in w


def test_verify_done_true(monkeypatch):
    _patch_llm(monkeypatch, returns='{"verified":true,"reason":"ok"}')
    ok, reason = asyncio.run(agent.verify_done("g", "page"))
    assert ok is True


def test_verify_done_error_false(monkeypatch):
    _patch_llm(monkeypatch, raises=RuntimeError("x"))
    ok, reason = asyncio.run(agent.verify_done("g", "page"))
    assert ok is False
