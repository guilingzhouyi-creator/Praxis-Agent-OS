"""LLM provider implementations — extracted from llm.py for modularity."""

from __future__ import annotations

import json
import logging
import os
import time

from l1.kernel.discovery import get_config
from l1.kernel.params.agent import LLM_CACHE_RETENTION_THRESHOLD
from l1.kernel.params.api import (
    ENV_ANTHROPIC_KEY,
    ENV_ANTHROPIC_MODEL,
    ENV_ANTHROPIC_URL,
    ENV_DEEPSEEK_KEY,
    ENV_LLM_WS_MODEL,
    ENV_LLM_WS_URL,
    ENV_OLLAMA_MODEL,
    ENV_OLLAMA_URL,
    ENV_OPENAI_KEY,
    ENV_OPENAI_MODEL,
    ENV_OPENAI_URL,
    FALLBACK_MODEL,
    LLM_HTTP_TIMEOUT,
    LLM_LIGHTWEIGHT_TIMEOUT,
    LLM_PROVIDER_CONTEXT_WINDOW,
    LLM_PROVIDER_MAX_TOKENS,
    LLM_PROVIDER_URLS,
)
from l1.kernel.params.system import LLM_DEFAULT_CONTEXT_WINDOW, LOG_TRUNC_60, LOG_TRUNC_200, MOCK_DELAY
from l1.kernel.prompts import get_prompt as _gp

from .http_pool import http_post

logger = logging.getLogger(__name__)


class _ProviderHelperMixin:
    """Shared helpers for LLM provider classes — eliminates duplicate _vault_key / _get_setting."""

    def _vault_key(self, provider: str, key: str = "api_key") -> str:
        try:
            from l4.vault.credential_vault import get_credential

            return get_credential(provider, key)
        except Exception:
            return ""

    def _get_setting(self, key: str, default: str) -> str:
        try:
            from l1.kernel.settings import get_settings

            return get_settings().get(key, default)
        except Exception:
            return default


class MockProvider:
    """Built-in mock LLM — no API key needed, for testing."""

    name = "mock"

    @property
    def capabilities(self) -> set[str]:
        return {"max_tokens", "temperature"}

    def probe(self) -> dict:
        return {"supports": self.capabilities, "context_window": LLM_DEFAULT_CONTEXT_WINDOW, "model": "mock"}

    def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = LLM_PROVIDER_MAX_TOKENS,
        user_id: str = "",
        cache_retention: str = "",
        **kwargs,
    ) -> dict:
        time.sleep(MOCK_DELAY)
        return {
            "content": f"[mock] analyzed: {prompt[:LOG_TRUNC_60]}...",
            "tokens": len(prompt) // 4,
            "model": "mock",
            "finish_reason": "stop",
        }

    def health(self) -> dict:
        return {"status": "ok", "model": "mock", "latency_ms": 0.0}


class OpenAIProvider(_ProviderHelperMixin):
    """OpenAI-compatible API (GPT, DeepSeek, etc.)."""

    name = "openai"

    @property
    def capabilities(self) -> set[str]:
        return {"max_tokens", "temperature", "reasoning_effort", "context_window", "tool_use", "streaming"}

    def probe(self) -> dict:
        caps = {"max_tokens", "temperature", "tool_use"}
        # Probe reasoning_effort with a minimal request
        try:
            self.generate("ping", reasoning_effort="low", max_tokens=1)
            caps.add("reasoning_effort")
        except Exception:
            logger.debug("llm_providers: reasoning_effort probe failed")
        # Probe thinking_budget — OpenAI does NOT support it
        try:
            self.generate("ping", thinking_budget=1, max_tokens=1)
            caps.add("thinking_budget")
        except Exception:
            logger.debug("llm_providers: thinking_budget probe failed")
        context_window = self._probe_context_window()
        return {"supports": caps, "context_window": context_window, "model": self.model}

    def _probe_context_window(self) -> int:
        model_lower = self.model.lower()
        if "128k" in model_lower:
            return 128000
        if "32k" in model_lower or "long" in model_lower:
            return 32768
        if "16k" in model_lower:
            return 16384
        return LLM_DEFAULT_CONTEXT_WINDOW  # default for modern OpenAI models

    def __init__(self, api_key: str = "", api_url: str = "", model: str = ""):
        self.api_key = (
            api_key
            or self._vault_key("openai")
            or os.environ.get(ENV_OPENAI_KEY, "")
            or os.environ.get(ENV_DEEPSEEK_KEY, "")
        )
        _urls = get_config("provider_urls") or {}
        self.api_url = (
            api_url
            or self._vault_key("openai", "api_url")
            or os.environ.get(
                ENV_OPENAI_URL, self._get_setting("llm.api_url", _urls.get("openai", LLM_PROVIDER_URLS["openai"]))
            )
        )
        self.model = (
            model
            or self._vault_key("openai", "model")
            or os.environ.get(ENV_OPENAI_MODEL, self._get_setting("llm.model", "<model>"))
        )

    def _api_call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = LLM_PROVIDER_MAX_TOKENS,
        user_id: str = "",
        cache_retention: float = 0,
    ) -> dict:
        body_dict = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            body_dict["tools"] = tools
        if user_id:
            body_dict["user_id"] = user_id
        if cache_retention >= LLM_CACHE_RETENTION_THRESHOLD:
            body_dict["prompt_cache_retention"] = "24h"
        body = json.dumps(body_dict, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        try:
            status, raw, _ = http_post(self.api_url, body, headers, LLM_HTTP_TIMEOUT)
            if status >= 400:
                return {
                    "content": "",
                    "tool_calls": [],
                    "tokens": 0,
                    "model": self.model,
                    "error": f"HTTP {status}: {raw.decode(errors='replace')[:LOG_TRUNC_200]}",
                }
            data = json.loads(raw)
            msg = data["choices"][0]["message"]
            usage = data.get("usage", {})
            rtok = (usage.get("output_tokens_details", {}) or {}).get("reasoning_tokens", 0)
            return {
                "content": msg.get("content", ""),
                "reasoning_content": msg.get("reasoning_content", ""),
                "reasoning_tokens": rtok,
                "tool_calls": msg.get("tool_calls", []),
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "tokens": usage.get("total_tokens", 0),
                "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
                "cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
                "model": data.get("model", self.model),
                "finish_reason": data["choices"][0].get("finish_reason", "stop"),
            }
        except Exception as e:
            return {"content": "", "tool_calls": [], "tokens": 0, "model": self.model, "error": str(e)}

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = 512, user_id: str = "", cache_retention: float = 0
    ) -> dict:
        return self._api_call(
            messages=[
                {"role": "system", "content": system or _gp("llm.fallback_system", "You are a helpful assistant.")},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            user_id=user_id,
            cache_retention=cache_retention,
        )

    def generate_with_messages(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = LLM_PROVIDER_MAX_TOKENS,
        user_id: str = "",
        cache_retention: float = 0,
    ) -> dict:
        return self._api_call(
            messages=messages, tools=tools, max_tokens=max_tokens, user_id=user_id, cache_retention=cache_retention
        )

    def health(self) -> dict:
        import time

        t0 = time.perf_counter()
        try:
            r = self._api_call(
                messages=[{"role": "user", "content": "Respond with OK"}],
                max_tokens=5,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            if r.get("error"):
                return {"status": "degraded", "model": self.model, "latency_ms": round(elapsed, 1), "error": r["error"]}
            return {"status": "ok", "model": self.model, "latency_ms": round(elapsed, 1)}
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {"status": "down", "model": self.model, "latency_ms": round(elapsed, 1), "error": str(e)}

    def embed(self, texts: list[str]) -> dict:
        """Embed texts via the OpenAI-compatible /embeddings endpoint.

        Returns ``{"success": True, "vectors": [[...], ...], "model": str}``
        or a graceful error dict so callers degrade to lexical retrieval.
        """
        if not texts:
            return {"success": False, "error": "empty text list"}
        if not self.api_key:
            return {"success": False, "error": "no api key for embeddings"}
        import urllib.request as req

        body = json.dumps({"model": self.model, "input": list(texts)}).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        url = self.api_url.rstrip("/") + "/embeddings"
        try:
            r = req.Request(url, data=body, headers=headers, method="POST")
            with req.urlopen(r, timeout=LLM_LIGHTWEIGHT_TIMEOUT) as resp:
                data = json.loads(resp.read().decode(errors="replace"))
            vectors = [
                item.get("embedding")
                for item in (data.get("data") or [])
                if isinstance(item, dict) and item.get("embedding")
            ]
            if not vectors:
                return {"success": False, "error": "no embeddings returned"}
            return {
                "success": True,
                "vectors": vectors,
                "model": self.model,
                "count": len(vectors),
                "dim": len(vectors[0]),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class AnthropicProvider(_ProviderHelperMixin):
    """Anthropic API (Claude)."""

    name = "anthropic"

    @property
    def capabilities(self) -> set[str]:
        return {"max_tokens", "temperature", "thinking_budget", "context_window", "tool_use", "vision"}

    def probe(self) -> dict:
        caps = {"max_tokens", "temperature", "tool_use", "vision"}
        # Probe thinking_budget
        try:
            self.generate("ping", thinking_budget=1, max_tokens=1)
            caps.add("thinking_budget")
        except Exception:
            logger.debug("llm_providers: thinking_budget probe failed")
        # Probe reasoning_effort — Anthropic does NOT support it
        try:
            self.generate("ping", reasoning_effort="low", max_tokens=1)
            caps.add("reasoning_effort")
        except Exception:
            logger.debug("llm_providers: reasoning_effort probe failed")
        cl = self._probe_context_window()
        return {"supports": caps, "context_window": cl, "model": self.model}

    def _probe_context_window(self) -> int:
        ml = self.model.lower()
        if "200k" in ml:
            return 200000
        if "100k" in ml:
            return 100000
        return 200000

    def __init__(self, api_key: str = "", api_url: str = "", model: str = "", cache_breakpoints: int = 4):
        self.api_key = api_key or self._vault_key("anthropic") or os.environ.get(ENV_ANTHROPIC_KEY, "")
        _urls = get_config("provider_urls") or {}
        self.api_url = (
            api_url
            or self._vault_key("anthropic", "api_url")
            or os.environ.get(
                ENV_ANTHROPIC_URL,
                self._get_setting("llm.api_url", _urls.get("anthropic", LLM_PROVIDER_URLS["anthropic"])),
            )
        )
        self.model = (
            model
            or self._vault_key("anthropic", "model")
            or os.environ.get(ENV_ANTHROPIC_MODEL, self._get_setting("llm.model", "<model>"))
        )
        self.cache_breakpoints = cache_breakpoints

    def _inject_cache_breakpoints(
        self, messages: list[dict], tools: list[dict] | None = None, anthropic: bool = False
    ) -> list[dict]:
        if self.cache_breakpoints <= 0:
            return messages
        result = list(messages)
        bp_remaining = self.cache_breakpoints

        def _tag(msg: dict) -> dict:
            if anthropic and isinstance(msg.get("content"), str):
                return {
                    **msg,
                    "content": [{"type": "text", "text": msg["content"], "cache_control": {"type": "ephemeral"}}],
                }
            return {**msg, "cache_control": {"type": "ephemeral"}}

        for i, msg in enumerate(result):
            if msg.get("role") == "system" and bp_remaining > 0:
                result[i] = _tag(msg)
                bp_remaining -= 1
                break
        if bp_remaining > 0:
            user_indices = [i for i, msg in enumerate(result) if msg.get("role") == "user"]
            for idx in user_indices[-bp_remaining:]:
                result[idx] = _tag(result[idx])
                bp_remaining -= 1
        return result

    def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = LLM_PROVIDER_MAX_TOKENS,
        user_id: str = "",
        tools: list[dict] | None = None,
    ) -> dict:
        messages = [{"role": "user", "content": prompt}]
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        system_content = system or _gp("llm.fallback_system", "You are a helpful assistant.")
        sys_bp = self._inject_cache_breakpoints([{"role": "system", "content": system_content}], anthropic=True)
        system_for_anthropic = (
            sys_bp[0]["content"] if sys_bp and sys_bp[0].get("content") != system_content else system_content
        )
        body_dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_for_anthropic,
            "messages": self._inject_cache_breakpoints(messages, tools, anthropic=True),
        }
        if tools:
            body_dict["tools"] = tools
        if user_id:
            body_dict["metadata"] = {"user_id": user_id}
        body = json.dumps(body_dict).encode()
        headers = {"Content-Type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        try:
            status, raw, _ = http_post(self.api_url, body, headers, LLM_LIGHTWEIGHT_TIMEOUT)
            if status >= 400:
                return {
                    "content": "",
                    "tokens": 0,
                    "model": FALLBACK_MODEL,
                    "error": f"HTTP {status}: {raw.decode(errors='replace')[:LOG_TRUNC_200]}",
                }
            data = json.loads(raw)
            content = data["content"][0]["text"]
            usage = data.get("usage", {})
            return {
                "content": content,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                "cache_hit_tokens": usage.get("cache_read_input_tokens", 0),
                "cache_miss_tokens": max(0, usage.get("input_tokens", 0) - usage.get("cache_read_input_tokens", 0)),
                "model": data.get("model", FALLBACK_MODEL),
                "finish_reason": "stop",
            }
        except Exception as e:
            return {"content": "", "tokens": 0, "model": FALLBACK_MODEL, "error": str(e)}

    def health(self) -> dict:
        import time

        t0 = time.perf_counter()
        try:
            result = self.generate("Respond with OK", max_tokens=5)
            elapsed = (time.perf_counter() - t0) * 1000
            if result.get("error"):
                return {
                    "status": "degraded",
                    "model": self.model,
                    "latency_ms": round(elapsed, 1),
                    "error": result["error"],
                }
            return {"status": "ok", "model": self.model, "latency_ms": round(elapsed, 1)}
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {"status": "down", "model": self.model, "latency_ms": round(elapsed, 1), "error": str(e)}


class OllamaProvider(_ProviderHelperMixin):
    """Local Ollama model via native API."""

    name = "ollama"

    @property
    def capabilities(self) -> set[str]:
        return {"max_tokens", "temperature", "context_window"}

    def probe(self) -> dict:
        caps = {"max_tokens", "temperature"}
        try:
            self.generate("ping", reasoning_effort="low", max_tokens=1)
            caps.add("reasoning_effort")
        except Exception:
            logger.debug("llm_providers: reasoning_effort probe failed")
        try:
            self.generate("ping", thinking_budget=1, max_tokens=1)
            caps.add("thinking_budget")
        except Exception:
            logger.debug("llm_providers: thinking_budget probe failed")
        return {"supports": caps, "context_window": LLM_PROVIDER_CONTEXT_WINDOW, "model": self.model}

    def __init__(self, api_url: str = "", model: str = ""):
        self.api_url = api_url or os.environ.get(
            ENV_OLLAMA_URL,
            self._get_setting(
                "llm.api_url", (get_config("provider_urls") or {}).get("ollama", LLM_PROVIDER_URLS["ollama"])
            ),
        )
        self.model = model or os.environ.get(ENV_OLLAMA_MODEL, self._get_setting("llm.model", "<model>"))

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = LLM_PROVIDER_MAX_TOKENS, user_id: str = "", **kwargs
    ) -> dict:
        messages = [
            {"role": "system", "content": system or _gp("llm.fallback_system", "You are a helpful assistant.")},
            {"role": "user", "content": prompt},
        ]
        body = json.dumps(
            {"model": self.model, "messages": messages, "stream": False, "options": {"num_predict": max_tokens}}
        ).encode()
        headers = {"Content-Type": "application/json"}
        try:
            status, raw, _ = http_post(f"{self.api_url}/api/chat", body, headers, LLM_LIGHTWEIGHT_TIMEOUT)
            if status >= 400:
                return {
                    "content": "",
                    "tokens": 0,
                    "model": self.model,
                    "error": f"HTTP {status}: {raw.decode(errors='replace')[:LOG_TRUNC_200]}",
                }
            data = json.loads(raw)
            msg = data.get("message", {})
            return {
                "content": msg.get("content", ""),
                "tokens": data.get("eval_count", 0),
                "model": self.model,
                "finish_reason": "stop",
            }
        except Exception as e:
            return {"content": "", "tokens": 0, "model": self.model, "error": str(e)}

    def health(self) -> dict:
        import time

        t0 = time.perf_counter()
        try:
            result = self.generate("Respond with OK", max_tokens=5)
            elapsed = (time.perf_counter() - t0) * 1000
            if result.get("error"):
                return {
                    "status": "degraded",
                    "model": self.model,
                    "latency_ms": round(elapsed, 1),
                    "error": result["error"],
                }
            return {"status": "ok", "model": self.model, "latency_ms": round(elapsed, 1)}
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {"status": "down", "model": self.model, "latency_ms": round(elapsed, 1), "error": str(e)}

    def embed(self, texts: list[str]) -> dict:
        """Embed texts via Ollama /api/embed (native embeddings endpoint).

        Returns ``{"success": True, "vectors": [[...], ...], "model": str}``
        or a graceful error dict so callers degrade to lexical retrieval.
        """
        if not texts:
            return {"success": False, "error": "empty text list"}
        body = json.dumps({"model": self.model, "input": list(texts)}).encode()
        headers = {"Content-Type": "application/json"}
        try:
            status, raw, _ = http_post(f"{self.api_url}/api/embed", body, headers, LLM_LIGHTWEIGHT_TIMEOUT)
            if status >= 400:
                return {"success": False, "error": f"HTTP {status}: {raw.decode(errors='replace')[:LOG_TRUNC_200]}"}
            data = json.loads(raw)
            vectors = data.get("embeddings") or []
            if not vectors:
                return {"success": False, "error": "no embeddings returned"}
            return {
                "success": True,
                "vectors": vectors,
                "model": self.model,
                "count": len(vectors),
                "dim": len(vectors[0]),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class WebSocketProvider(_ProviderHelperMixin):
    """WebSocket-based LLM provider."""

    name = "websocket"

    def __init__(self, url: str = "", model: str = ""):
        self.url = url or os.environ.get(ENV_LLM_WS_URL, self._get_setting("llm.api_url", ""))
        self.model = model or os.environ.get(ENV_LLM_WS_MODEL, self._get_setting("llm.model", ""))

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = LLM_PROVIDER_MAX_TOKENS, user_id: str = "", **kwargs
    ) -> dict:
        import urllib.request as req

        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "system": system or _gp("llm.fallback_system", "You are a helpful assistant."),
                "max_tokens": max_tokens,
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        try:
            r = req.urlopen(
                req.Request(self.url, data=body, headers=headers, method="POST"), timeout=LLM_LIGHTWEIGHT_TIMEOUT
            )
            return {"content": r.read().decode(), "tokens": 0, "model": self.model}
        except Exception as e:
            return {"content": "", "tokens": 0, "model": self.model, "error": str(e)}

    def health(self) -> dict:
        import time

        t0 = time.perf_counter()
        try:
            result = self.generate("Respond with OK", max_tokens=5)
            elapsed = (time.perf_counter() - t0) * 1000
            if result.get("error"):
                return {
                    "status": "degraded",
                    "model": self.model,
                    "latency_ms": round(elapsed, 1),
                    "error": result["error"],
                }
            return {"status": "ok", "model": self.model, "latency_ms": round(elapsed, 1)}
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {"status": "down", "model": self.model, "latency_ms": round(elapsed, 1), "error": str(e)}
