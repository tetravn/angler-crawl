"""Bỏ litellm nên LLM_BASE_URL không còn default. Chưa cấu hình phải báo lỗi rõ ràng
ngay tại chỗ, thay vì gửi request tới chuỗi rỗng rồi chết bằng lỗi httpx khó hiểu."""
import asyncio

import pytest

from app import clients, llm_stream

_MSGS = [{"role": "user", "content": "x"}]


def _boom(*a, **kw):
    raise AssertionError("không được gọi HTTP khi LLM chưa cấu hình")


@pytest.mark.parametrize("missing", ["base_url", "model"])
def test_llm_chat_thieu_cau_hinh_thi_raise(monkeypatch, missing):
    monkeypatch.setattr(clients, "LLM_STREAM", False)
    monkeypatch.setattr(clients, "_http", _boom)
    monkeypatch.setattr(clients, "LLM_BASE_URL", "" if missing == "base_url" else "http://llm.test/v1")
    monkeypatch.setattr(clients, "LLM_MODEL", "" if missing == "model" else "m")
    with pytest.raises(RuntimeError, match="LLM chưa cấu hình"):
        asyncio.run(clients.llm_chat(_MSGS))


@pytest.mark.parametrize("missing", ["base_url", "model"])
def test_stream_chat_thieu_cau_hinh_thi_raise(monkeypatch, missing):
    monkeypatch.setattr(llm_stream, "LLM_BASE_URL", "" if missing == "base_url" else "http://llm.test/v1")
    monkeypatch.setattr(llm_stream, "LLM_MODEL", "" if missing == "model" else "m")
    with pytest.raises(RuntimeError, match="LLM chưa cấu hình"):
        asyncio.run(llm_stream.stream_chat(_MSGS))
