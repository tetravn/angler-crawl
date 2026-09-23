import pytest

from app import clients, llm_stream


@pytest.fixture(autouse=True)
def _llm_configured(monkeypatch):
    """LLM_BASE_URL và LLM_MODEL không còn default (trước đây trỏ sẵn vào service
    litellm nội bộ với model-group angler-smart).

    Test nào muốn kiểm nhánh "chưa cấu hình" thì tự đặt lại về chuỗi rỗng.
    """
    for mod in (clients, llm_stream):
        monkeypatch.setattr(mod, "LLM_BASE_URL", "http://llm.test/v1")
        monkeypatch.setattr(mod, "LLM_MODEL", "test-model")
