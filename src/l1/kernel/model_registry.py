"""ModelRegistry — unified LLM model discovery, registration, and routing.

Provides:
  - Auto-discovery of available providers from environment and settings
  - Unified model listing (provider + model name + status)
  - Factory method to construct provider instances by name
  - Config-driven routing and fallback

Architecture:

    model_registry.discover()
         │
         ├── scan environment variables → discover providers
         ├── scan SettingsCenter → discover YAML-configured providers
         └── optional: network discovery (ollama list, etc.)
         │
         ▼
    model_registry.list() → [{"provider", "model", "status", "api_url"}, ...]
    model_registry.get_provider(name, model) → LLMProvider instance
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from l1.kernel.discovery import get_config
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
)

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Descriptor for an available model."""
    provider: str          # "openai", "anthropic", "ollama", ...
    model: str             # model name, e.g. "gpt-4o", "llama3"
    api_url: str           # endpoint URL
    api_key: str = ""      # empty = not configured
    status: str = "unknown"  # "ok" | "degraded" | "down" | "unknown"
    source: str = "env"    # "env" | "yaml" | "network" | "manual"


# ── Provider discovery descriptors ──
# Each entry describes how to discover a provider from env vars + settings.
# Format: (provider_name, env_key, env_url, env_model, default_url, api_key_env)

_PROVIDER_DISCOVERY: list[tuple[str, str, str, str, str, str]] = [
    ("openai",    ENV_OPENAI_KEY,    ENV_OPENAI_URL,    ENV_OPENAI_MODEL,
     "https://api.openai.com/v1/chat/completions",
     ENV_OPENAI_KEY),
    ("deepseek",  ENV_DEEPSEEK_KEY,  "",                "",
     "https://api.openai.com/v1/chat/completions",
     ENV_DEEPSEEK_KEY),
    ("anthropic", ENV_ANTHROPIC_KEY, ENV_ANTHROPIC_URL, ENV_ANTHROPIC_MODEL,
     "https://api.anthropic.com/v1/messages",
     ENV_ANTHROPIC_KEY),
    ("ollama",    "",                ENV_OLLAMA_URL,    ENV_OLLAMA_MODEL,
     "http://localhost:11434",
     ""),
    ("websocket", "",                ENV_LLM_WS_URL,   ENV_LLM_WS_MODEL,
     "",
     ""),
]


# ── Provider factory registry ──
# Maps provider name → callable(LLMProvider_subclass, url, model, key, cache_breakpoints)
# Registering a new provider type is a one-line addition here; no method changes needed.

_PROVIDER_HANDLERS: dict[str, Callable[..., Any]] = {
    "ollama":    lambda cls, url, model, key, _c: cls(url, model),
    "openai":    lambda cls, url, model, key, _c: cls(key, url, model),
    "deepseek":  lambda cls, url, model, key, _c: cls(key, url, model),
    "anthropic": lambda cls, url, model, key, cache: cls(key, url, model, cache),
    "websocket": lambda cls, url, model, key, _c: cls(url, model, key),
}


class ModelRegistry:
    """Unified model registry — discovery, listing, factory, routing.

    Provider classes are registered at boot via ``register_provider_class()``,
    eliminating the need for Kernel to import L4 private variables.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._models: dict[str, list[ModelInfo]] = {}  # provider → [ModelInfo, ...]
        self._discovered = False
        self._provider_classes: dict[str, type] = {}  # provider → LLMProvider subclass

    # ── Discovery ────────────────────────────────────────────────────────

    def discover(self) -> int:
        """Scan environment variables + settings for available providers.

        Returns the number of models discovered.
        """
        count = 0
        with self._lock:
            self._models.clear()
            for provider, env_key, env_url, env_model, default_url, api_key_env in _PROVIDER_DISCOVERY:
                models = self._discover_provider(
                    provider, env_key, env_url, env_model, default_url, api_key_env,
                )
                if models:
                    self._models[provider] = models
                    count += len(models)

            # Also try loading from SettingsCenter
            self._discover_from_settings()

            self._discovered = True
        logger.info("model_registry: discovered %d models across %d providers",
                     count, len(self._models))
        return count

    def _discover_provider(self, provider: str, env_key: str, env_url: str,
                           env_model: str, default_url: str, api_key_env: str) -> list[ModelInfo]:
        """Discover a single provider from env vars + discovery config."""
        api_key = os.environ.get(env_key, "") if env_key else ""
        api_key = api_key or (os.environ.get(api_key_env, "") if api_key_env else "")
        env_val = os.environ.get(env_url, "") if env_url else ""
        if env_val:
            url = env_val
        else:
            purls = get_config("provider_urls") or {}
            url = purls.get(provider, default_url)
        model = os.environ.get(env_model, "") if env_model else ""

        if not api_key and provider not in ("ollama", "mock", "websocket"):
            # Provider configured but no API key — mark as degraded
            if url:
                return [ModelInfo(
                    provider=provider, model=model or f"{provider}-default",
                    api_url=url, api_key="", status="degraded",
                    source="env",
                )]
            return []

        if not url:
            return []

        return [ModelInfo(
            provider=provider,
            model=model or f"{provider}-default",
            api_url=url,
            api_key=api_key,
            status="ok" if api_key else "degraded",
            source="env",
        )]

    def _discover_from_settings(self) -> None:
        """Discover providers configured via YAML / SettingsCenter."""
        try:
            from l1.kernel.settings import get_settings
            s = get_settings()
            provider = s.get("llm.provider", "")
            model = s.get("llm.model", "")
            api_url = s.get("llm.api_url", "")
            api_key = s.get("llm.api_key", "")
            if provider and api_url:
                existing = self._models.get(provider, [])
                info = ModelInfo(
                    provider=provider, model=model or f"{provider}-yaml",
                    api_url=api_url, api_key=api_key or "",
                    status="ok" if api_key else "degraded",
                    source="yaml",
                )
                existing.append(info)
                self._models[provider] = existing
        except Exception as e:
            logger.debug("model_registry: settings discover: %s", e)

    # ── Query ────────────────────────────────────────────────────────────

    def list(self, provider: str = "") -> list[ModelInfo]:
        """List all discovered models. Optionally filter by provider name."""
        if not self._discovered:
            self.discover()
        with self._lock:
            if provider:
                return list(self._models.get(provider, []))
            result = []
            for models in self._models.values():
                result.extend(models)
            return result

    def list_providers(self) -> list[str]:
        """List all provider names with at least one discovered model."""
        if not self._discovered:
            self.discover()
        with self._lock:
            return sorted(self._models.keys())

    def get_provider_config(self, provider: str, model: str = "") -> dict | None:
        """Get the best configuration for a provider/model combination.

        Returns dict with keys: provider, model, api_url, api_key
        or None if no matching provider is discovered.
        """
        if not self._discovered:
            self.discover()
        with self._lock:
            models = self._models.get(provider, [])
        if not models:
            return None
        # Prefer exact model match, otherwise first available
        for info in models:
            if model and info.model == model and info.status == "ok":
                return {"provider": info.provider, "model": info.model,
                        "api_url": info.api_url, "api_key": info.api_key}
        # Fall back to first ok model
        for info in models:
            if info.status == "ok":
                return {"provider": info.provider, "model": info.model,
                        "api_url": info.api_url, "api_key": info.api_key}
        # Last resort: first model even if degraded
        info = models[0]
        return {"provider": info.provider, "model": info.model,
                "api_url": info.api_url, "api_key": info.api_key}

    def get_fallback(self, provider: str, model: str = "") -> dict | None:
        """Get fallback configuration when primary provider is unavailable.

        Tries other providers in order, excluding the given provider.
        """
        if not self._discovered:
            self.discover()
        all_providers = self.list_providers()
        for alt in all_providers:
            if alt == provider:
                continue
            cfg = self.get_provider_config(alt, model)
            if cfg and cfg.get("api_key"):
                return cfg
        return None

    # ── Register provider class (called at boot by L4 wiring) ──

    def register_provider_class(self, name: str, provider_cls: type) -> None:
        """Register an LLM provider class for later construction.

        Called at boot by L4 wiring to avoid Kernel→L4 imports.
        """
        with self._lock:
            self._provider_classes[name] = provider_cls

    def list_registered_providers(self) -> list[str]:
        """List all registered provider class names."""
        with self._lock:
            return sorted(self._provider_classes.keys())

    # ── Build provider instance ──────────────────────────────────────────

    def build_provider(self, provider: str, model: str = "",
                       api_key: str = "", api_url: str = "",
                       cache_breakpoints: int = 4) -> Any | None:
        """Construct a provider instance by name.

        Returns an LLMProvider subclass instance, or None if the provider
        is not registered.
        """
        with self._lock:
            cls = self._provider_classes.get(provider)
        if cls is None:
            logger.warning("model_registry: unknown provider '%s'", provider)
            return None

        # Resolve config: prefer explicit args, fall back to discovered config
        resolved_key = api_key
        resolved_url = api_url
        resolved_model = model

        if not resolved_key or not resolved_url:
            cfg = self.get_provider_config(provider, model)
            if cfg:
                resolved_key = resolved_key or cfg.get("api_key", "")
                resolved_url = resolved_url or cfg.get("api_url", "")
                resolved_model = resolved_model or cfg.get("model", "")

        try:
            handler = _PROVIDER_HANDLERS.get(provider)
            if handler:
                return handler(cls, resolved_url, resolved_model,
                               resolved_key, cache_breakpoints)
            # Fallback for unknown providers: try kwargs, then no-arg
            try:
                return cls(api_key=resolved_key, api_url=resolved_url,
                           model=resolved_model)
            except Exception:
                return cls()
        except Exception as e:
            logger.warning("model_registry: failed to build '%s': %s", provider, e)
            return None

    def reset(self) -> None:
        """Clear all discovered models."""
        with self._lock:
            self._models.clear()
            self._discovered = False


# ── Singleton ──

_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
        _registry.discover()
    return _registry


def reset_registry() -> None:
    global _registry
    if _registry:
        _registry.reset()
    _registry = None
