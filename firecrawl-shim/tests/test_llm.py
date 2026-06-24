import asyncio

from app import clients


class _FakeResp:
    headers = {"x-litellm-model-api-base": "http://ollama.internal:11434"}

    def raise_for_status(self):
        pass

    def json(self):
        return {"model": "groq/llama-3.1-8b-instant",
                "choices": [{"message": {"content": "hi"}}]}


def _fake_http(captured):
    class _Client:
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["body"] = json
            captured["headers"] = headers
            return _FakeResp()
    return _Client()


def test_llm_chat_explicit_model_and_temperature(monkeypatch):
    cap = {}
    monkeypatch.setattr(clients, "_http", lambda: _fake_http(cap))
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    out = asyncio.run(clients.llm_chat(
        [{"role": "user", "content": "x"}], model="angler-fast", temperature=0.3))
    assert out == "hi"
    assert cap["body"]["model"] == "angler-fast"
    assert cap["body"]["temperature"] == 0.3
    assert cap["body"]["response_format"] == {"type": "json_object"}
    assert cap["url"].endswith("/chat/completions")


def test_llm_chat_defaults_to_llm_model(monkeypatch):
    cap = {}
    monkeypatch.setattr(clients, "_http", lambda: _fake_http(cap))
    monkeypatch.setattr(clients, "LLM_MODEL", "angler-smart")
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    asyncio.run(clients.llm_chat([{"role": "user", "content": "x"}]))
    assert cap["body"]["model"] == "angler-smart"
    assert cap["body"]["temperature"] == 0      # default


def test_llm_chat_no_json_mode_omits_response_format(monkeypatch):
    cap = {}
    monkeypatch.setattr(clients, "_http", lambda: _fake_http(cap))
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    asyncio.run(clients.llm_chat([{"role": "user", "content": "x"}], json_mode=False))
    assert "response_format" not in cap["body"]


def test_llm_chat_json_native_off_omits_response_format(monkeypatch):
    # LLM_JSON_NATIVE=False → KHÔNG gửi response_format dù json_mode=True (cho model thinking)
    cap = {}
    monkeypatch.setattr(clients, "_http", lambda: _fake_http(cap))
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    monkeypatch.setattr(clients, "LLM_JSON_NATIVE", False)
    asyncio.run(clients.llm_chat([{"role": "user", "content": "x"}], json_mode=True))
    assert "response_format" not in cap["body"]


def test_llm_chat_timeout_uses_dedicated_client(monkeypatch):
    cap = {}

    def fake_ct(timeout):
        cap["timeout"] = timeout
        return _fake_http(cap)

    monkeypatch.setattr(clients, "_client_with_timeout", fake_ct)
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    out = asyncio.run(clients.llm_chat(
        [{"role": "user", "content": "x"}], timeout=300))
    assert out == "hi"
    assert cap["timeout"] == 300


def test_llm_chat_no_timeout_uses_default_http(monkeypatch):
    cap = {}
    monkeypatch.setattr(clients, "_http", lambda: _fake_http(cap))
    monkeypatch.setattr(clients, "_client_with_timeout",
                        lambda t: (_ for _ in ()).throw(AssertionError("không được gọi")))
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    asyncio.run(clients.llm_chat([{"role": "user", "content": "x"}]))
    assert cap["url"].endswith("/chat/completions")


def test_llm_chat_uses_stream_when_enabled(monkeypatch):
    called = {}

    async def fake_stream(messages, **kw):
        called["kw"] = kw
        return "streamed"

    monkeypatch.setattr(clients, "stream_chat", fake_stream)
    monkeypatch.setattr(clients, "LLM_STREAM", True)
    out = asyncio.run(clients.llm_chat([{"role": "user", "content": "x"}], model="angler-fast"))
    assert out == "streamed"
    assert called["kw"]["model"] == "angler-fast"


def test_llm_chat_non_stream_when_disabled(monkeypatch):
    cap = {}
    monkeypatch.setattr(clients, "_http", lambda: _fake_http(cap))
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    out = asyncio.run(clients.llm_chat([{"role": "user", "content": "x"}]))
    assert out == "hi"
    assert cap["url"].endswith("/chat/completions")
    assert "stream" not in cap["body"]            # đường POST non-stream
