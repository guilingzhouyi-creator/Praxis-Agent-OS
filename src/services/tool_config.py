"""ToolConfig — YAML-driven tool definition loader.

Replaces auto_discover + register_tools() boilerplate.
Loads tools.yaml at boot, registers all ToolSpec into TOOL_REGISTRY,
and provides chain-filter API for three-tier tool ring integration.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Any

import yaml

from .tool_spec import ToolSpec, ParamSpec, ReturnSpec, register, TOOL_REGISTRY, ToolRing
from kernel.params.kernel import RING_NAME_MAP, RING_NUM_MAP

logger = logging.getLogger(__name__)

_DEFAULT_YAML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tools.yaml")


def _resolve_handler(handler_path: str) -> Any:
    """Resolve 'tools._files._cmd_read_file' → actual function."""
    parts = handler_path.split(".")
    module_path = ".".join(parts[:-1])
    func_name = parts[-1]
    try:
        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        logger.warning("handler resolve failed: %s — %s", handler_path, e)
        return None


def _parse_param(p: dict) -> ParamSpec:
    return ParamSpec(
        name=p["name"],
        type=p.get("type", "string"),
        required=p.get("required", False),
        default=p.get("default"),
        description=p.get("description", ""),
    )


_LAYER_RING_MAP = {"layer_1": ToolRing.RING_1, "layer_2": ToolRing.RING_2_5, "layer_3": ToolRing.RING_3}


class ToolConfig:
    """YAML-driven tool registry — loads, filters, and queries tools."""

    _loaded = False

    # ── Initialization ──

    @classmethod
    def load(cls, yaml_path: str = "") -> int:
        """Load tools.yaml and register all tools into TOOL_REGISTRY.

        Supports hierarchical layout:
          layer_X → domain → tool_name → {description, handler, params, danger}
        """
        path = yaml_path or _DEFAULT_YAML_PATH
        if not os.path.exists(path):
            logger.warning("tools.yaml not found at %s", path)
            return 0

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            logger.warning("tools.yaml: root must be a dict")
            return 0

        count = 0
        for layer_key, domains in data.items():
            if layer_key.startswith("_"):
                continue
            ring = _LAYER_RING_MAP.get(layer_key, ToolRing.RING_1)
            if not isinstance(domains, dict):
                continue
            for domain, tools in domains.items():
                if not isinstance(tools, dict):
                    continue
                for name, defn in tools.items():
                    if name.startswith("_"):
                        continue
                    try:
                        spec = cls._build_spec(name, defn, domain, ring)
                        if spec:
                            register(spec)
                            count += 1
                    except Exception as e:
                        logger.warning("tool_config: skip '%s': %s", name, e)

        cls._loaded = True
        logger.info("tool_config: loaded %d tools from %s", count, path)
        return count

    @classmethod
    def reload(cls, yaml_path: str = "") -> int:
        """Hot-reload tools.yaml (dev). Clears registry first."""
        TOOL_REGISTRY.clear()
        cls._loaded = False
        return cls.load(yaml_path)

    @classmethod
    def _build_spec(cls, name: str, defn: dict, domain: str, ring: str) -> ToolSpec | None:
        handler = None
        handler_path = defn.get("handler", "")
        if handler_path:
            handler = _resolve_handler(handler_path)

        params_raw = defn.get("params", [])
        params = [_parse_param(p) if isinstance(p, dict) else ParamSpec(name=p) for p in params_raw]

        # default danger=0 for ring_1, danger=1 for ring_2_5, danger=4 for ring_3
        # Only apply ring-based defaults when YAML did not specify danger
        # (explicit danger: 0 must be preserved).
        danger = defn.get("danger")
        if danger is None:
            if ring == ToolRing.RING_1:
                danger = 0
            elif ring == ToolRing.RING_2_5:
                danger = 1
            else:
                danger = 4

        returns_raw = defn.get("returns", {})
        returns = ReturnSpec(
            type=returns_raw.get("type", "object"),
            description=returns_raw.get("description", ""),
            properties=returns_raw.get("properties", {
                "success": "bool", "data": "any", "error": "string?",
            }),
        )

        return ToolSpec(
            name=name,
            description=defn.get("description", ""),
            category=domain,
            ring=ring,
            danger=danger,
            parameters=params,
            returns=returns,
            handler=handler,
            parallel_safe=ring == ToolRing.RING_1,
            sandbox_profile=defn.get("sandbox_profile"),
            metadata={
                "composite": defn.get("composite"),
                "handler_path": handler_path,
                "layer": ring,
            },
        )

    # ── Query ──

    @classmethod
    def all(cls) -> list[ToolSpec]:
        return list(TOOL_REGISTRY.values())

    @classmethod
    def get(cls, name: str) -> ToolSpec | None:
        return TOOL_REGISTRY.get(name)

    @classmethod
    def has(cls, name: str) -> bool:
        return name in TOOL_REGISTRY

    # ── Filters ──

    @classmethod
    def by_ring(cls, ring: str | int) -> list[ToolSpec]:
        if isinstance(ring, int):
            # single source: kernel.params.RING_NAME_MAP (int→str)
            ring = RING_NAME_MAP.get(ring, "RING_1")
        return [t for t in cls.all() if t.ring == ring]

    @classmethod
    def by_ring_up_to(cls, max_ring: int) -> list[ToolSpec]:
        # single source: kernel.params.RING_NUM_MAP (str→int)
        return [t for t in cls.all() if RING_NUM_MAP.get(t.ring, 0) <= max_ring]

    @classmethod
    def by_category(cls, category: str) -> list[ToolSpec]:
        return [t for t in cls.all() if t.category == category]

    @classmethod
    def by_danger(cls, min_d: int = 0, max_d: int = 5) -> list[ToolSpec]:
        return [t for t in cls.all() if min_d <= t.danger <= max_d]

    @classmethod
    def by_names(cls, names: set[str]) -> list[ToolSpec]:
        name_set = set(names)
        return [t for t in cls.all() if t.name in name_set]

    @classmethod
    def available_for(cls, agent_id: str) -> list[ToolSpec]:
        """ToolPolicy-filtered tool list."""
        from .tool_policy import ToolPolicy
        return [t for t in cls.all() if ToolPolicy.is_allowed(agent_id, t.name)]

    # ── Derivative data sets ──

    @classmethod
    def write_tool_names(cls) -> frozenset[str]:
        return frozenset(
            t.name for t in cls.all()
            if t.danger >= 1 or t.ring != ToolRing.RING_1
        )

    @classmethod
    def terminal_tool_names(cls) -> frozenset[str]:
        return frozenset(
            t.name for t in cls.all()
            if t.category == "terminal"
        )

    @classmethod
    def file_tool_names(cls) -> frozenset[str]:
        return frozenset(
            t.name for t in cls.all()
            if t.category == "file"
        )

    @classmethod
    def completions(cls) -> dict[str, str]:
        return {t.name: t.description[:60] for t in cls.all()}

    # ── LLM integration ──

    @classmethod
    def for_llm(cls, tools: list[ToolSpec]) -> list[dict]:
        return [t.to_api_format() for t in tools]

    # ── Utility ──

    @classmethod
    def resolve_handler(cls, tool_name: str) -> Any | None:
        spec = cls.get(tool_name)
        if spec and spec.handler:
            return spec.handler
        if spec:
            hpath = spec.metadata.get("handler_path", "")
            if hpath:
                return _resolve_handler(hpath)
        return None
