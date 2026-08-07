"""L3AModelConfig — model provider config with inheritance chain.

Priority (highest to lowest):
  1. Per-prompt override                    (sessions.prompt model_config=)
  2. L3A own config                         (/l3a model set)
  3. Global default                         (config/praxis.yaml llm:)
  4. Compile-time default                   (params/l3a.py)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import params as _p


@dataclass
class L3AModelConfig:
    """L3AModelConfig — l3 a model config record (provider, model, max_tokens, temperature, reasoning_effort)."""
    provider: str = ""
    model: str = ""
    max_tokens: int = _p.L3A_MODEL_MAX_TOKENS
    temperature: float = _p.L3A_MODEL_TEMPERATURE
    reasoning_effort: str = ""
    thinking_budget: int = 0
    _source: str = "default"

    def resolve(self, override: dict | None = None) -> dict:
        """Resolve the effective model dict, merging an optional per-prompt override."""
        effective: dict[str, Any] = {}
        if self.provider:
            effective["provider"] = self.provider
        if self.model:
            effective["model"] = self.model
        effective["max_tokens"] = self.max_tokens
        effective["temperature"] = self.temperature
        if self.reasoning_effort:
            effective["reasoning_effort"] = self.reasoning_effort
        if self.thinking_budget:
            effective["thinking_budget"] = self.thinking_budget
        if override:
            effective.update(override)
        return effective

    def apply_global(self, global_config: dict) -> None:
        """Fill unset fields from the global LLM config dict."""
        if not self.provider:
            self.provider = global_config.get("provider", "")
            self._source = "global"
        if not self.model:
            self.model = global_config.get("model", "")
            self._source = "global" if not self.provider else self._source
        self.max_tokens = global_config.get("max_tokens", self.max_tokens)
        self.temperature = global_config.get("temperature", self.temperature)
        if not self.reasoning_effort:
            self.reasoning_effort = global_config.get("reasoning_effort", "")
        if not self.thinking_budget:
            self.thinking_budget = int(global_config.get("thinking_budget", 0))

    def set(self, key: str, value: Any) -> None:
        """Set one config field, coercing thinking_budget to int and marking the source as l3a."""
        if key in ("provider", "model", "max_tokens", "temperature",
                   "reasoning_effort", "thinking_budget"):
            if key == "thinking_budget":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"thinking_budget must be int, got {value!r}")
            setattr(self, key, value)
            self._source = "l3a"

    def show(self) -> dict:
        """Return the config as a dict for display."""
        return {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "thinking_budget": self.thinking_budget,
            "source": self._source,
        }
