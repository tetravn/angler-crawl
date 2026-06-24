import json

from app import agent


def test_js_click_index_uses_attr():
    js = agent._js_click_index(7)
    assert '[data-ai-idx="7"]' in js and "click()" in js


def test_js_type_index_escapes():
    js = agent._js_type_index(3, 'a"b')
    assert '[data-ai-idx="3"]' in js
    assert json.dumps('a"b') in js and "input" in js


def test_action_to_js_index_mapping():
    assert agent._action_to_js({"action": "click", "index": 2}) is not None
    assert '[data-ai-idx="2"]' in agent._action_to_js({"action": "click", "index": 2})[0]
    assert agent._action_to_js({"action": "type", "index": 1, "value": "x"}) is not None
    assert agent._action_to_js({"action": "scroll"})[0].count("scrollBy") == 1
    assert agent._action_to_js({"action": "click"}) is None          # thiếu index
    assert agent._action_to_js({"action": "type", "value": "x"}) is None
    assert agent._action_to_js({"action": "wait"}) is None
    assert agent._action_to_js({"action": "done"}) is None


def _result_with(elements):
    return {"markdown": "md", "js_execution_result": {"success": True, "results": [elements]}}


def test_parse_elements_ok():
    els = [{"idx": 0, "tag": "button", "text": "OK"}]
    assert agent._parse_elements(_result_with(els)) == els


def test_parse_elements_missing_or_fail():
    assert agent._parse_elements({"markdown": "x"}) == []
    assert agent._parse_elements({"js_execution_result": {"success": False}}) == []
    assert agent._parse_elements({"js_execution_result": {"success": True, "results": [None]}}) == []


def test_parse_elements_finds_list_among_nulls():
    # act call: js_code = [actionSnippet, snapshot] → results = [null, [elements]]
    els = [{"idx": 1, "tag": "a", "text": "Login"}]
    r = {"js_execution_result": {"success": True, "results": [None, els]}}
    assert agent._parse_elements(r) == els


def test_render_observation_marks_new_and_caps():
    els = [{"idx": i, "tag": "button", "text": f"b{i}"} for i in range(3)]
    out = agent._render_observation(els, "PAGEMD", new_idx={1})
    assert "INTERACTIVE ELEMENTS:" in out
    assert "*[1]" in out and "[0]" in out
    assert "PAGE TEXT:" in out and "PAGEMD" in out


def test_render_observation_cap(monkeypatch):
    monkeypatch.setattr(agent, "AGENT_MAX_ELEMENTS", 2)
    els = [{"idx": i, "tag": "a", "text": f"x{i}"} for i in range(5)]
    out = agent._render_observation(els, "", new_idx=set())
    assert "(+3 phần tử nữa" in out


def test_signature_and_changed():
    a = agent._obs_signature("same")
    b = agent._obs_signature("same")
    c = agent._obs_signature("diff")
    assert a == b and a != c
    assert agent._page_changed(a, c) is True
    assert agent._page_changed(a, b) is False


def test_diff_new():
    prev = [{"idx": 0, "tag": "a", "text": "Home"}]
    cur = [{"idx": 0, "tag": "a", "text": "Home"}, {"idx": 1, "tag": "button", "text": "New"}]
    assert agent._diff_new(prev, cur) == {1}


def test_is_stuck_repeat():
    log = [{"action": "click", "index": 1, "obs_sig": "S", "changed": True}] * 3
    assert agent._is_stuck(log, 3) is True


def test_is_stuck_oscillation():
    log = [
        {"action": "click", "index": 1, "obs_sig": "A", "changed": True},
        {"action": "click", "index": 2, "obs_sig": "B", "changed": True},
        {"action": "click", "index": 1, "obs_sig": "A", "changed": True},
        {"action": "click", "index": 2, "obs_sig": "B", "changed": True},
    ]
    assert agent._is_stuck(log, 3) is True


def test_is_stuck_no_change():
    log = [{"action": "scroll", "index": None, "obs_sig": f"S{i}", "changed": False} for i in range(3)]
    assert agent._is_stuck(log, 3) is True


def test_is_stuck_false_when_diverse():
    log = [
        {"action": "click", "index": 1, "obs_sig": "A", "changed": True},
        {"action": "click", "index": 2, "obs_sig": "B", "changed": True},
        {"action": "scroll", "index": None, "obs_sig": "C", "changed": True},
    ]
    assert agent._is_stuck(log, 3) is False
