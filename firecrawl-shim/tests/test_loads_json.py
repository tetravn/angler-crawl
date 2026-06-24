import pytest

from app import clients


def test_bare_json_object():
    assert clients.loads_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_bare_json_list():
    assert clients.loads_json('[1, 2, 3]') == [1, 2, 3]


def test_fenced_json():
    out = "```json\n{\"queries\": [\"a\", \"b\"]}\n```"
    assert clients.loads_json(out) == {"queries": ["a", "b"]}


def test_fenced_no_lang():
    out = "```\n{\"x\": true}\n```"
    assert clients.loads_json(out) == {"x": True}


def test_prose_preamble_then_object():
    out = 'Here is the JSON you asked for:\n{"results": [{"index": 0}]}'
    assert clients.loads_json(out) == {"results": [{"index": 0}]}


def test_reasoning_then_object():
    out = "Let me think... the answer is {\"answered\": true, \"confidence\": 0.8} done."
    assert clients.loads_json(out) == {"answered": True, "confidence": 0.8}


def test_garbage_raises():
    with pytest.raises(ValueError):
        clients.loads_json("not json at all, no braces here")


def test_empty_raises():
    with pytest.raises(ValueError):
        clients.loads_json("")
