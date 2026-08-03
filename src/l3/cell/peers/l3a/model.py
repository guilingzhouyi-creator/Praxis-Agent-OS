"""L3AModelConfig — model provider config with inheritance chain.

Priority (highest to lowest):
  1. Per-prompt override                    (sessions.prompt model_config=)
  2. L3A own config                         (/l3a model set)
  3. Global default                         (config/praxis.yaml llm:)
  4. Compile-time default                   (params/l3a.py)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import params as _p


@dataclass
class L3AModelConfig:
    provider: str = ""
    model: str = ""
    max_tokens: int = _p.L3A_MODEL_MAX_TOKENS
    temperature: float = _p.L3A_MODEL_TEMPERATURE
    _source: str = "default"

    def resolve(self, override: dict | None = None) -> dict:
        effective = {}
        if self.provider:
            effective["provider"] = self.provider
        if self.model:
            effective["model"] = self.model
        effective["max_tokens"] = self.max_tokens
        effective["temperature"] = self.temperature
        if override:
            effective.update(override)
        return effective

    def apply_global(self, global_config: dict) -> None:
        if not self.provider:
            self.provider = global_config.get("provider", "")
            self._source = "global"
        if not self.model:
            self.model = global_config.get("model", "")
            self._source = "global" if not self.provider else self._source
        self.max_tokens = global_config.get("max_tokens", self.max_tokens)
        self.temperature = global_config.get("temperature", self.temperature)

    def set(self, key: str, value: Any) -> None:
        if key in ("provider", "model", "max_tokens", "temperature"):
            setattr(self, key, value)
            self._source = "l3a"

    def show(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "source": self._source,
        }
