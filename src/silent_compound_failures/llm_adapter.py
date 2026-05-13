from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import requests


@dataclass
class LLMResult:
    content: Optional[str]
    latency_s: float
    completion_tokens: int
    finish_reason: Optional[str]
    http_status: Optional[int]
    error: Optional[str]


class LLMAdapter(Protocol):
    def chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        timeout: int,
    ) -> LLMResult:
        ...

    def rlm_decompose(
        self,
        prompt: str,
        timeout: int,
    ) -> tuple[Optional[str], float, Optional[dict]]:
        ...


def _bearer_headers(token: Optional[str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class OpenAICompatAdapter:
    """POST {base_url}/v1/chat/completions. Works for Ollama, vLLM, OpenAI, etc."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None, temperature: float = 0.1):
        self.base_url = (base_url or os.environ.get("RLM_HUB_URL", "http://localhost:11434")).rstrip("/")
        self.token = token if token is not None else os.environ.get("RLM_TOKEN")
        self.temperature = temperature

    def chat(self, model: str, messages: list[dict], max_tokens: int, timeout: int) -> LLMResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }
        start = time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=_bearer_headers(self.token),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return LLMResult(None, time.monotonic() - start, 0, None, None, str(exc))

        latency = time.monotonic() - start
        if resp.status_code != 200:
            return LLMResult(None, latency, 0, None, resp.status_code, f"HTTP {resp.status_code}")

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            completion_tokens = data.get("usage", {}).get("completion_tokens", 0) or 0
            finish_reason = data["choices"][0].get("finish_reason")
        except (ValueError, KeyError, IndexError) as exc:
            return LLMResult(None, latency, 0, None, resp.status_code, f"malformed response: {exc}")

        return LLMResult(content, latency, completion_tokens, finish_reason, 200, None)

    def rlm_decompose(self, prompt: str, timeout: int) -> tuple[Optional[str], float, Optional[dict]]:
        # OpenAI-compatible endpoints don't expose a trace endpoint; return chat content with no trace.
        result = self.chat(
            model=os.environ.get("RLM_MODEL", "qwen2.5-coder:14b"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            timeout=timeout,
        )
        return result.content, result.latency_s, None


class RLMHubAdapter:
    """POST {base_url}/v1/rlm. Returns (content, latency, trace_dict_or_None)."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = (base_url or os.environ.get("RLM_HUB_URL", "http://localhost:1337")).rstrip("/")
        self.token = token if token is not None else os.environ.get("RLM_TOKEN")

    def chat(self, model: str, messages: list[dict], max_tokens: int, timeout: int) -> LLMResult:
        # Delegate to OpenAI-compat path on the same hub if it supports it.
        return OpenAICompatAdapter(base_url=self.base_url, token=self.token).chat(model, messages, max_tokens, timeout)

    def rlm_decompose(self, prompt: str, timeout: int) -> tuple[Optional[str], float, Optional[dict]]:
        payload = {"prompt": prompt}
        start = time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/v1/rlm",
                json=payload,
                headers=_bearer_headers(self.token),
                timeout=timeout,
            )
        except requests.RequestException:
            return None, time.monotonic() - start, None

        latency = time.monotonic() - start
        if resp.status_code != 200:
            return None, latency, None

        try:
            data = resp.json()
        except ValueError:
            return None, latency, None

        content = data.get("content")
        trace = data.get("trace")
        # Empty dict trace counts as "no trace" for downstream consumers.
        if not trace:
            trace = None
        return content, latency, trace


def default_adapter() -> LLMAdapter:
    """Pick adapter from env. RLM_HUB_KIND=rlm uses RLMHubAdapter; default is OpenAI-compat."""
    kind = os.environ.get("RLM_HUB_KIND", "openai").lower()
    if kind == "rlm":
        return RLMHubAdapter()
    return OpenAICompatAdapter()
