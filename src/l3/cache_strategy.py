"""CacheStrategy — config-driven LLM prefix cache adaptation.

Behavior is driven by praxis.yaml → llm.cache section:

  llm:
    cache:
      defaults:
        optimize_prompt: true    # wrap in [System]/[Task]
        forward_user_id: false
        anthropic_format: false  # use top-level system field
      openai:
        optimize_prompt: true
        forward_user_id: true
      deepseek:
        optimize_prompt: true
        forward_user_id: true
      anthropic:
        optimize_prompt: false
        forward_user_id: true
        anthropic_format: true
      ollama:
        optimize_prompt: false

New providers can be added in YAML without any Python code change.
Plugins can still register custom strategies via register_strategy().
"""

from __future__ import annotations

from typing import Any

from l4.llm import optimize_prompt

# ── Global config (loaded from praxis.yaml at boot) ──

_cache_config: dict[str, dict] = {}


def load_cache_config(cfg: dict) -> None:
    """Load per-provider cache config from praxis.yaml → llm.cache."""
    global _cache_config
    if not cfg:
        return
    _cache_config.clear()
    _cache_config.update(cfg)
    # Ensure defaults exist
    if "defaults" not in _cache_config:
        _cache_config["defaults"] = {}
    d = _cache_config["defaults"]
    d.setdefault("optimize_prompt", True)
    d.setdefault("forward_user_id", False)
    d.setdefault("anthropic_format", False)


# ── Config-driven strategy (covers all built-in providers) ──

class ConfigCacheStrategy:
    """Single strategy class driven by praxis.yaml → llm.cache config.

    Each provider's behavior is defined by three boolean flags:
      optimize_prompt  — wrap in [System]/[Task] sections
      forward_user_id  — pass user_id to provider for KV isolation
      anthropic_format — flag for Anthropic cache_control injection
    """

    def __init__(self, provider: str):
        self.provider = provider
        defaults = _cache_config.get("defaults", {})
        specific = _cache_config.get(provider, {})
        self._opts = {**defaults, **specific}

    def optimize(self, prompt: str, system: str,
                 user_id: str = "") -> tuple[str, str, dict[str, Any]]:
        extra: dict[str, Any] = {}
        if self._opts.get("forward_user_id", False) and user_id:
            extra["user_id"] = user_id
        if self._opts.get("anthropic_format", False):
            extra["_anthropic_format"] = True
        if self._opts.get("optimize_prompt", True):
            prompt, system = optimize_prompt(prompt, system)
        return prompt, system, extra


# ── Plugin strategy registry (for custom strategies) ──

_plugin_strategies: dict[str, Any] = {}


def register_strategy(provider_name: str, strategy: Any) -> None:
    """Register a custom cache strategy (for plugins with special needs)."""
    _plugin_strategies[provider_name.strip().lower()] = strategy


# ── Public API ──

def get_strategy(provider_name: str) -> ConfigCacheStrategy | Any:
    """Get cache strategy for a provider.

    Priority:
      1. Plugin-registered custom strategy
      2. Config-driven strategy (works for any provider in YAML)
    """
    name = provider_name.strip().lower()
    custom = _plugin_strategies.get(name)
    if custom:
        return custom
    return ConfigCacheStrategy(name)
