"""LLM provider implementations — extracted from llm.py for modularity."""
from __future__ import annotations

import json
import logging
import os
import time

from kernel.params.api import LLM_HTTP_TIMEOUT, LLM_LIGHTWEIGHT_TIMEOUT, LLM_PROVIDER_URLS
from kernel.params.system import MOCK_DELAY
from kernel.prompts import get_prompt as _gp

logger = logging.getLogger(__name__)


class MockProvider:
    """Built-in mock LLM — no API key needed, for testing."""
    name = "mock"

    def generate(self, prompt: str, system: str = "",
                 max_tokens: int = 512, user_id: str = "",
                 cache_retention: str = "", **kwargs) -> dict:
        time.sleep(MOCK_DELAY)
        return {
            "content": f"[mock] analyzed: {prompt[:60]}...",
            "tokens": len(prompt) // 4,
            "model": "mock",
            "finish_reason": "stop",
        }


class OpenAIProvider:
    """OpenAI-compatible API (GPT, DeepSeek, etc.)."""
    name = "openai"

    def __init__(self, api_key: str = "", api_url: str = "", model: str = ""):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "")
        self.api_url = api_url or os.environ.get("OPENAI_API_URL", self._get_setting("llm.api_url", LLM_PROVIDER_URLS["openai"]))
        self.model = model or os.environ.get("OPENAI_MODEL", self._get_setting("llm.model", "<model>"))

    def _get_setting(self, key: str, default: str) -> str:
        try:
            from kernel.settings import get_settings
            return get_settings().get(key, default)
        except Exception:
            return default

    def _api_call(self, messages: list[dict], tools: list[dict] | None = None,
                   max_tokens: int = 512, user_id: str = "",
                   cache_retention: float = 0) -> dict:
        import urllib.request as req
        body_dict = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            body_dict["tools"] = tools
        if user_id:
            body_dict["user_id"] = user_id
        if cache_retention >= 86400:
            body_dict["prompt_cache_retention"] = "24h"
        body = json.dumps(body_dict, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        try:
            r = req.urlopen(req.Request(self.api_url, data=body, headers=headers, method="POST"), timeout=LLM_HTTP_TIMEOUT)
            data = json.loads(r.read())
            msg = data["choices"][0]["message"]
            usage = data.get("usage", {})
            return {"content": msg.get("content", ""), "tool_calls": msg.get("tool_calls", []),
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "tokens": usage.get("total_tokens", 0),
                    "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
                    "cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
                    "model": data.get("model", self.model),
                    "finish_reason": data["choices"][0].get("finish_reason", "stop")}
        except Exception as e:
            return {"content": "", "tool_calls": [], "tokens": 0, "model": self.model, "error": str(e)}

    def generate(self, prompt: str, system: str = "", max_tokens: int = 512,
                 user_id: str = "", cache_retention: float = 0) -> dict:
        return self._api_call(
            messages=[{"role": "system", "content": system or _gp("llm.fallback_system", "You are a helpful assistant.")},
                      {"role": "user", "content": prompt}],
            max_tokens=max_tokens, user_id=user_id, cache_retention=cache_retention)

    def generate_with_messages(self, messages: list[dict], tools: list[dict] | None = None,
                                max_tokens: int = 512, user_id: str = "",
                                cache_retention: float = 0) -> dict:
        return self._api_call(messages=messages, tools=tools, max_tokens=max_tokens,
                              user_id=user_id, cache_retention=cache_retention)


class AnthropicProvider:
    """Anthropic API (Claude)."""
    name = "anthropic"

    def __init__(self, api_key: str = "", api_url: str = "", model: str = "", cache_breakpoints: int = 4):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.api_url = api_url or os.environ.get("ANTHROPIC_API_URL",
                       self._get_setting("llm.api_url", LLM_PROVIDER_URLS["anthropic"]))
        self.model = model or os.environ.get("ANTHROPIC_MODEL",
                       self._get_setting("llm.model", "<model>"))
        self.cache_breakpoints = cache_breakpoints

    def _get_setting(self, key: str, default: str) -> str:
        try:
            from kernel.settings import get_settings
            return get_settings().get(key, default)
        except Exception:
            return default

    def _inject_cache_breakpoints(self, messages: list[dict], tools: list[dict] | None = None,
                                   anthropic: bool = False) -> list[dict]:
        if self.cache_breakpoints <= 0:
            return messages
        result = list(messages)
        bp_remaining = self.cache_breakpoints
        def _tag(msg: dict) -> dict:
            if anthropic and isinstance(msg.get("content"), str):
                return {**msg, "content": [{"type": "text", "text": msg["content"],
                                             "cache_control": {"type": "ephemeral"}}]}
            return {**msg, "cache_control": {"type": "ephemeral"}}
        for i, msg in enumerate(result):
            if msg.get("role") == "system" and bp_remaining > 0:
                result[i] = _tag(msg); bp_remaining -= 1; break
        if bp_remaining > 0:
            user_indices = [i for i, msg in enumerate(result) if msg.get("role") == "user"]
            for idx in user_indices[-bp_remaining:]:
                result[idx] = _tag(result[idx]); bp_remaining -= 1
        return result

    def generate(self, prompt: str, system: str = "",
                 max_tokens: int = 512, user_id: str = "",
                 tools: list[dict] | None = None) -> dict:
        import urllib.request as req
        messages = [{"role": "user", "content": prompt}]
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        system_content = system or _gp("llm.fallback_system", "You are a helpful assistant.")
        sys_bp = self._inject_cache_breakpoints([{"role": "system", "content": system_content}], anthropic=True)
        system_for_anthropic = sys_bp[0]["content"] if sys_bp and sys_bp[0].get("content") != system_content else system_content
        body_dict = {"model": self.model, "max_tokens": max_tokens,
                     "system": system_for_anthropic,
                     "messages": self._inject_cache_breakpoints(messages, tools, anthropic=True)}
        if tools: body_dict["tools"] = tools
        if user_id: body_dict["metadata"] = {"user_id": user_id}
        body = json.dumps(body_dict).encode()
        headers = {"Content-Type": "application/json", "x-api-key": self.api_key,
                   "anthropic-version": "2023-06-01"}
        try:
            r = req.urlopen(req.Request(self.api_url, data=body, headers=headers, method="POST"),
                            timeout=LLM_LIGHTWEIGHT_TIMEOUT)
            data = json.loads(r.read())
            content = data["content"][0]["text"]
            usage = data.get("usage", {})
            return {"content": content,
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    "cache_hit_tokens": usage.get("cache_read_input_tokens", 0),
                    "cache_miss_tokens": max(0, usage.get("input_tokens", 0) - usage.get("cache_read_input_tokens", 0)),
                    "model": data.get("model", "claude-3-haiku"), "finish_reason": "stop"}
        except Exception as e:
            return {"content": "", "tokens": 0, "model": "claude-3-haiku", "error": str(e)}


class OllamaProvider:
    """Local Ollama model via native API."""
    name = "ollama"

    def __init__(self, api_url: str = "", model: str = ""):
        self.api_url = api_url or os.environ.get("OLLAMA_URL", self._get_setting("llm.api_url", LLM_PROVIDER_URLS["ollama"]))
        self.model = model or os.environ.get("OLLAMA_MODEL", self._get_setting("llm.model", "<model>"))

    def _get_setting(self, key: str, default: str) -> str:
        try:
            from kernel.settings import get_settings
            return get_settings().get(key, default)
        except Exception:
            return default

    def generate(self, prompt: str, system: str = "",
                 max_tokens: int = 512, user_id: str = "",
                 **kwargs) -> dict:
        import urllib.request as req
        messages = [{"role": "system", "content": system or _gp("llm.fallback_system", "You are a helpful assistant.")},
                    {"role": "user", "content": prompt}]
        body = json.dumps({"model": self.model, "messages": messages,
                           "stream": False, "options": {"num_predict": max_tokens}}).encode()
        headers = {"Content-Type": "application/json"}
        try:
            r = req.urlopen(req.Request(f"{self.api_url}/api/chat", data=body, headers=headers, method="POST"),
                            timeout=LLM_LIGHTWEIGHT_TIMEOUT)
            data = json.loads(r.read())
            msg = data.get("message", {})
            return {"content": msg.get("content", ""),
                    "tokens": data.get("eval_count", 0),
                    "model": self.model, "finish_reason": "stop"}
        except Exception as e:
            return {"content": "", "tokens": 0, "model": self.model, "error": str(e)}


class WebSocketProvider:
    """WebSocket-based LLM provider."""
    name = "websocket"

    def __init__(self, url: str = "", model: str = ""):
        self.url = url or os.environ.get("LLM_WS_URL", self._get_setting("llm.api_url", ""))
        self.model = model or os.environ.get("LLM_WS_MODEL", self._get_setting("llm.model", ""))

    def _get_setting(self, key: str, default: str) -> str:
        try:
            from kernel.settings import get_settings
            return get_settings().get(key, default)
        except Exception:
            return default

    def generate(self, prompt: str, system: str = "",
                 max_tokens: int = 512, user_id: str = "",
                 **kwargs) -> dict:
        import urllib.request as req
        body = json.dumps({"model": self.model, "prompt": prompt,
                           "system": system or _gp("llm.fallback_system", "You are a helpful assistant."),
                           "max_tokens": max_tokens}).encode()
        headers = {"Content-Type": "application/json"}
        try:
            r = req.urlopen(req.Request(self.url, data=body, headers=headers,
                                        method="POST"), timeout=LLM_LIGHTWEIGHT_TIMEOUT)
            return {"content": r.read().decode(), "tokens": 0, "model": self.model}
        except Exception as e:
            return {"content": "", "tokens": 0, "model": self.model, "error": str(e)}
