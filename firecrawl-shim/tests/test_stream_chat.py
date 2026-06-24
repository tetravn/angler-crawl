import asyncio

import pytest

from app import llm_stream
from app import clients


class _Resp:
    def __init__(self, lines, headers=None, delay=0.0):
        self._lines, self.headers, self._delay = lines, (headers or {}), delay

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for ln in self._lines:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield ln


class _CM:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _Client:
    def __init__(self, resp):
        self._resp = resp

    def stream(self, method, url, json=None, headers=None):
        return _CM(self._resp)


def _patch(monkeypatch, resp):
    monkeypatch.setattr(clients, "_http", lambda: _Client(resp))


def test_stream_json_native_off_omits_response_format(monkeypatch):
    cap = {}

    class _CapClient:
        def __init__(self, resp):
            self._resp = resp

        def stream(self, method, url, json=None, headers=None):
            cap["body"] = json
            return _CM(self._resp)

    resp = _Resp(["data: [DONE]"])
    monkeypatch.setattr(clients, "_http", lambda: _CapClient(resp))
    monkeypatch.setattr(llm_stream, "LLM_JSON_NATIVE", False)
    asyncio.run(llm_stream.stream_chat([{"role": "user", "content": "x"}], json_mode=True))
    assert "response_format" not in cap["body"]
    assert cap["body"]["stream"] is True


def test_stream_json_native_on_includes_response_format(monkeypatch):
    cap = {}

    class _CapClient:
        def __init__(self, resp):
            self._resp = resp

        def stream(self, method, url, json=None, headers=None):
            cap["body"] = json
            return _CM(self._resp)

    resp = _Resp(["data: [DONE]"])
    monkeypatch.setattr(clients, "_http", lambda: _CapClient(resp))
    monkeypatch.setattr(llm_stream, "LLM_JSON_NATIVE", True)
    asyncio.run(llm_stream.stream_chat([{"role": "user", "content": "x"}], json_mode=True))
    assert cap["body"]["response_format"] == {"type": "json_object"}


def test_aggregates_and_calls_on_token(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
    ]
    _patch(monkeypatch, _Resp(lines))
    got = []
    out = asyncio.run(llm_stream.stream_chat(
        [{"role": "user", "content": "x"}], json_mode=False,
        on_token=lambda t: _collect(got, t)))
    assert out == "Hello"
    assert got == ["Hel", "lo"]


async def _collect(buf, t):
    buf.append(t)


def test_stall_aborts(monkeypatch):
    monkeypatch.setattr(llm_stream, "STREAM_STALL_TIMEOUT", 0.05)
    lines = ['data: {"choices":[{"delta":{"content":"hi"}}]}']
    _patch(monkeypatch, _Resp(lines, delay=0.2))      # mỗi dòng chậm 0.2s > 0.05
    with pytest.raises(llm_stream.StreamAborted):
        asyncio.run(llm_stream.stream_chat([{"role": "user", "content": "x"}], json_mode=False))


def test_monitor_abort_propagates(monkeypatch):
    # ép guard repetition nổ
    monkeypatch.setattr(llm_stream, "STREAM_MAX_REPEAT", 3)
    lines = [
        'data: {"choices":[{"delta":{"content":"spam spam "}}]}',
        'data: {"choices":[{"delta":{"content":"spam spam "}}]}',
        "data: [DONE]",
    ]
    _patch(monkeypatch, _Resp(lines))
    with pytest.raises(llm_stream.StreamAborted):
        asyncio.run(llm_stream.stream_chat([{"role": "user", "content": "x"}], json_mode=False))
