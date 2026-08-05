"""ModelService — unified LLM model configuration service.

Resolves model specs across a configurable inheritance chain:
  per-call override > per-spec > platform-default > cell > global-llm

Each spec is a named reference resolved from SettingsCenter config,
with environment variable interpolation and credential injection.

Architecture:
  ModelService (singleton)
    ├── resolve(spec_name, overrides) → LLMConfig
    │     inheritance chain: overrides > yaml spec > platform default > llm global
    ├── inject_credentials(config) → config (with api_key from vault)
    └── health_check(provider_name) → {"status": "ok"|"error"}
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from l1.kernel.ports import LLMConfig

logger = logging.getLogger(__name__)


_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def _interpolate_env(value: Any) -> Any:
    """Replace ${VAR_NAME:-default} patterns with env var values."""
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            var = m.group(1)
            default = m.group(2) or ""
            return os.environ.get(var, default)
        return _ENV_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


def _deep_merge(*dicts: dict) -> dict:
    """Merge dicts right-to-left.  Later dicts override earlier ones."""
    result: dict = {}
    for d in dicts:
        for k, v in d.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = _deep_merge(result[k], v)
            else:
                result[k] = v
    return result


class ModelService:
    """Central model configuration resolver.

    Reads model specs from SettingsCenter (populated by praxis.yaml model_spec:
    section and API runtime overrides).  Resolves inheritance chains and injects
    credentials from CredentialVault.

    Usage:
      ms = ModelService()
      config = ms.resolve("subagent.security-auditor",
                          overrides={"reasoning_effort": "high"})
      engine = get_engine(config)
    """

    def __init__(self):
        self._settings = None
        self._vault = None

    # ── Lazy deps ───────────────────────────────────────────────

    def _settings_center(self) -> Any:
        if self._settings is None:
            try:
                from l3.config.settings_center import get_center
                self._settings = get_center()
            except Exception:
                from unittest.mock import MagicMock
                self._settings = MagicMock()
                self._settings.get.return_value = None
        return self._settings

    def _credential_vault(self) -> Any:
        if self._vault is None:
            try:
                from l4.vault.credential_vault import get_credential
                self._vault_vault = get_credential
            except Exception:
                self._vault_vault = lambda p, k: None
            self._vault = True
        return self._vault_vault

    # ── Public API ──────────────────────────────────────────────

    def resolve(self, spec_name: str = "",
                overrides: dict | None = None) -> LLMConfig:
        """Resolve a named model spec to an LLMConfig.

        Resolution cascade (higher priority wins):
          1. overrides (per-call)
          2. model_spec.{spec_name} (from SettingsCenter)
          3. model_spec default for the platform (subagent/scout/r4/convention)
          4. llm global (llm.provider, llm.model, etc.)

        Returns LLMConfig populated with resolved values.
        """
        sc = self._settings_center()

        # 1. Collect layers
        layers: list[dict] = []

        # Base: global llm config
        global_llm = self._read_dict(sc, "llm") or {}
        layers.append(global_llm)

        # Named spec (e.g. "subagent.security-auditor", "scout", "r4_agent")
        spec_config = self._resolve_spec(sc, spec_name)
        if spec_config:
            layers.append(spec_config)

        # Overrides (highest)
        if overrides:
            layers.append(dict(overrides))

        # 2. Merge (right wins)
        merged = _deep_merge(*layers)

        # 3. Environment variable interpolation
        merged = _interpolate_env(merged)

        # 4. Credential injection
        self._inject_credentials(merged)

        # 5. Clamp reasoning to admin caps (mirrors ThinkQuotaRegistry so the
        #    model_spec path honors the same think.max_* ceilings as Cell peers)
        self._clamp_reasoning(sc, merged)

        # 6. Build LLMConfig
        return LLMConfig(
            provider=merged.get("provider", "mock"),
            model=merged.get("model", ""),
            api_url=merged.get("api_url", ""),
            api_key=merged.get("api_key", ""),
            max_tokens=int(merged.get("max_tokens", 2048)),
            temperature=float(merged.get("temperature", 0.3)),
            reasoning_effort=merged.get("reasoning_effort", "none"),
            thinking_budget=int(merged.get("thinking_budget", 0)),
        )

    @staticmethod
    def _clamp_reasoning(sc: Any, merged: dict) -> None:
        """Clamp thinking_budget and reasoning_effort to think.max_* caps.

        In-place. Mirrors ThinkQuotaRegistry.resolve clamping so executors
        resolved via model_spec (scout/l3a/subagent/r4) stay under the same
        admin ceilings as Cell peer agents. Clamps are logged as warnings.
        """
        try:
            from l1.kernel.params.api import THINK_MAX_BUDGET, THINK_MAX_REASONING
            max_budget = int(sc.get("think.max_budget", THINK_MAX_BUDGET))
            max_reasoning = str(sc.get("think.max_reasoning", THINK_MAX_REASONING))
        except Exception:
            return
        if "thinking_budget" in merged:
            merged["thinking_budget"] = max(0, int(merged["thinking_budget"]))
            if merged["thinking_budget"] > max_budget:
                logger.warning(
                    "model_service: thinking_budget %d clamped to %d (think.max_budget)",
                    merged["thinking_budget"], max_budget)
                merged["thinking_budget"] = max_budget
        effort = merged.get("reasoning_effort", "none")
        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        current = rank.get(str(effort), 0)
        if current > rank.get(max_reasoning, 3):
            logger.warning(
                "model_service: reasoning_effort %r clamped to %r (think.max_reasoning)",
                effort, max_reasoning)
            merged["reasoning_effort"] = max_reasoning

    def resolve_dict(self, spec_name: str = "",
                     overrides: dict | None = None) -> dict:
        """Resolve and return a raw dict (for passing as **model_kwargs)."""
        cfg = self.resolve(spec_name, overrides)
        return {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "reasoning_effort": cfg.reasoning_effort,
            "thinking_budget": cfg.thinking_budget,
        }

    # ── Named strategy packs (runtime switching) ──────────────────────

    def resolve_strategy_pack(self, strategy_name: str) -> dict | None:
        """Read a named strategy pack definition (reasoning keys only).

        Returns a dict of {reasoning_effort, thinking_budget, ...} from
        ``model_spec.strategies.{name}`` (praxis.yaml), or None when the
        strategy is unknown or disabled.
        """
        sc = self._settings_center()
        defn = self._read_dict(
            sc, "model_spec.strategies." + strategy_name, leaf_only=True)
        if not defn:
            return None
        if defn.get("enabled") is False:
            return None
        return {k: v for k, v in defn.items()
                if k in ("reasoning_effort", "thinking_budget",
                         "max_tokens", "temperature")}

    def apply_strategy(self, spec_name: str, strategy_name: str) -> dict:
        """Apply a named strategy pack to an executor.

        Strategy definitions live under ``model_spec.strategies.{name}``
        (praxis.yaml). Keys are written into the exact layer
        ``model_spec.{spec_name}.{key}`` (L3, persisted), which outranks the
        executor defaults in the resolution cascade — immediate effect.
        """
        sc = self._settings_center()
        defn = self.resolve_strategy_pack(strategy_name)
        if defn is None:
            return {"success": False,
                    "error": f"unknown or disabled strategy: {strategy_name}"}
        written = []
        for key, value in defn.items():
            sc.set(f"model_spec.{spec_name}.{key}", value)
            written.append(key)
        sc.set(f"model_spec.{spec_name}.strategy", strategy_name)
        return {"success": True, "spec": spec_name, "strategy": strategy_name,
                "applied": written}

    def clear_strategy(self, spec_name: str) -> dict:
        """Remove a strategy's exact-layer overrides, restoring defaults."""
        sc = self._settings_center()
        removed = []
        all_ = sc.all()
        prefix = f"model_spec.{spec_name}."
        protected = ("defaults", "specs", "strategies")
        for key in list(all_.keys()):
            if not key.startswith(prefix):
                continue
            if any(key.startswith(prefix + d + ".") for d in protected):
                continue
            sc.reset(key)
            removed.append(key)
        return {"success": True, "spec": spec_name,
                "cleared": removed, "restored": "defaults"}

    def current_strategy(self, spec_name: str) -> dict:
        """Report the active strategy and exact-layer overrides for a spec."""
        sc = self._settings_center()
        active = sc.get(f"model_spec.{spec_name}.strategy", "")
        exact = self._read_dict(sc, "model_spec." + spec_name, leaf_only=True)
        exact = {k: v for k, v in (exact or {}).items() if k != "strategy"}
        return {"spec": spec_name, "strategy": active or "defaults",
                "overrides": exact or {}}

    def health_check(self, provider_name: str) -> dict:
        """Quick health check for a provider by name."""
        try:
            config = self.resolve(overrides={"provider": provider_name})
            from l4.llm.llm import get_engine
            engine = get_engine(config)
            if hasattr(engine._provider, "health"):
                return engine._provider.health()
            return {"status": "unknown", "message": "no health() method"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Internal ────────────────────────────────────────────────

    def _resolve_spec(self, sc: Any, spec_name: str) -> dict | None:
        """Resolve a dot-separated spec name through SettingsCenter.

        Config is stored as flat keys by _store_tree.  Multiple path
        patterns are tried:
          model_spec.{spec_name}
          model_spec.{prefix}.specs.{name}   (for subagent.platform.name)
          model_spec.{prefix}.defaults       (for platform defaults)
        """
        if not spec_name:
            return None

        parts = spec_name.split(".")

        # 1. Try exact: model_spec.{spec_name} (leaf keys only, so a
        #    model_spec.l3a.defaults.* subtree is not mistaken for an
        #    exact l3a spec)
        full = self._read_dict(sc, "model_spec." + spec_name, leaf_only=True)
        if full:
            return full

        # 2. Try model_spec.{prefix}.specs.{name}
        if len(parts) >= 2:
            full = self._read_dict(
                sc, f"model_spec.{parts[0]}.specs.{parts[-1]}", leaf_only=True)
            if full:
                return full

        # 3. Try platform defaults: model_spec.{prefix}.defaults
        if len(parts) >= 1:
            defaults = self._read_dict(
                sc, "model_spec." + parts[0] + ".defaults", leaf_only=True)
            if defaults:
                return defaults

        return None

    def _read_dict(self, sc: Any, prefix: str, leaf_only: bool = False) -> dict | None:
        """Read a flattened key prefix from SettingsCenter as a dict.

        SettingsCenter values like llm.provider, llm.model are stored as
        flat keys.  This reconstructs them into nested dicts. With
        ``leaf_only``, only direct children (sub_key without further dots)
        are collected — used to avoid matching deeper subtrees such as
        ``model_spec.x.defaults.*`` when resolving the exact spec ``x``.
        """
        try:
            result = {}
            all_ = sc.all() if hasattr(sc, "all") else {}
            for key, value in all_.items():
                if key.startswith(prefix + "."):
                    sub_key = key[len(prefix) + 1:]
                    if leaf_only and "." in sub_key:
                        continue
                    result[sub_key] = value
            return result if result else None
        except Exception:
            return None

    def _inject_credentials(self, config: dict) -> None:
        """Inject api_key from CredentialVault if not already set."""
        if config.get("api_key"):
            return
        provider = config.get("provider", "")
        if not provider:
            return
        try:
            vault = self._credential_vault()
            key = vault(provider, "api_key")
            if key:
                config["api_key"] = key
        except Exception:
            logger.debug("model_service: vault key lookup failed")


# ── Singleton ──

_service: ModelService | None = None


def get_service() -> ModelService:
    """Get the ModelService singleton (lazy init)."""
    global _service
    if _service is None:
        _service = ModelService()
    return _service


def reset_service() -> None:
    global _service
    _service = None
