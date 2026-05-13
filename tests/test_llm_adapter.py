from unittest.mock import patch, MagicMock

import requests

from silent_compound_failures.llm_adapter import (
    LLMResult,
    OpenAICompatAdapter,
    RLMHubAdapter,
    default_adapter,
)


def _mock_response(status_code: int, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


class TestOpenAICompatAdapter:
    def test_chat_success(self):
        body = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 5},
        }
        adapter = OpenAICompatAdapter(base_url="http://x", token="t")
        with patch("silent_compound_failures.llm_adapter.requests.post", return_value=_mock_response(200, body)):
            result = adapter.chat("m", [{"role": "user", "content": "hi"}], 10, 30)
        assert isinstance(result, LLMResult)
        assert result.content == "hello"
        assert result.completion_tokens == 5
        assert result.finish_reason == "stop"
        assert result.http_status == 200
        assert result.error is None

    def test_chat_http_error(self):
        adapter = OpenAICompatAdapter(base_url="http://x", token="t")
        with patch("silent_compound_failures.llm_adapter.requests.post", return_value=_mock_response(500)):
            result = adapter.chat("m", [], 10, 30)
        assert result.content is None
        assert result.http_status == 500
        assert "HTTP 500" in (result.error or "")

    def test_chat_timeout(self):
        adapter = OpenAICompatAdapter(base_url="http://x", token="t")
        with patch(
            "silent_compound_failures.llm_adapter.requests.post",
            side_effect=requests.Timeout("timed out"),
        ):
            result = adapter.chat("m", [], 10, 1)
        assert result.content is None
        assert result.http_status is None
        assert "timed out" in (result.error or "").lower()


class TestRLMHubAdapter:
    def test_decompose_success(self):
        body = {"content": "answer", "trace": {"n_subtasks": 3, "backends": ["x"]}}
        adapter = RLMHubAdapter(base_url="http://x", token="t")
        with patch("silent_compound_failures.llm_adapter.requests.post", return_value=_mock_response(200, body)):
            content, latency, trace = adapter.rlm_decompose("p", 30)
        assert content == "answer"
        assert trace is not None
        assert trace["n_subtasks"] == 3

    def test_decompose_no_trace(self):
        body = {"content": "answer"}
        adapter = RLMHubAdapter(base_url="http://x", token="t")
        with patch("silent_compound_failures.llm_adapter.requests.post", return_value=_mock_response(200, body)):
            content, latency, trace = adapter.rlm_decompose("p", 30)
        assert content == "answer"
        assert trace is None


def test_default_adapter_env_switch(monkeypatch):
    monkeypatch.setenv("RLM_HUB_KIND", "rlm")
    assert isinstance(default_adapter(), RLMHubAdapter)
    monkeypatch.setenv("RLM_HUB_KIND", "openai")
    assert isinstance(default_adapter(), OpenAICompatAdapter)
