"""ConfigDiscovery — auto-discovery & declarative config registry.

Allows structural configuration to be declared in YAML files and
auto-discovered at boot, rather than hardcoded in Python modules.

Three-tier merging (lowest to highest priority):
  1. Params defaults (via discovery() defaults)
  2. YAML config files (auto-discovered from config/discovery/)
  3. Runtime overrides (via register/set)

Usage::

    from l1.kernel.discovery import discover, register

    # Register a config source with defaults
    register("build_detectors", {
        "pip": {"cmd": ["python", "-m", "build"]},
        "cargo": {"cmd": ["cargo", "build"]},
    })

    # Auto-discover all YAML overrides — layer on top of defaults
    discover()

    # Read merged config
    from l1.kernel.discovery import get_config
    detectors = get_config("build_detectors")
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────

_registry: dict[str, dict[str, Any]] = {}
"""Merged config registry: name → {key: value, ...}."""

_sources: dict[str, dict[str, Any]] = {}
"""Registered defaults per source name."""

_DISCOVERY_DIRS: list[str] = []
"""Directories scanned for YAML config snippets."""


def register(name: str, defaults: Any) -> None:
    """Register a config section with its Python-side defaults.

    Args:
        name: Config section name (e.g. ``"build_detectors"``).
        defaults: Default value (dict, list, or scalar) that may be
            overridden by YAML. Dicts are copied; non-dict values are
            stored as-is (discover() replaces them wholesale).
    """
    if isinstance(defaults, dict):
        _sources[name] = dict(defaults)
        _registry[name] = dict(defaults)
    else:
        _sources[name] = defaults
        _registry[name] = defaults


def register_discovery_dir(path: str) -> None:
    """Add a directory to scan for ``.yaml`` config snippets."""
    if path not in _DISCOVERY_DIRS:
        _DISCOVERY_DIRS.append(path)


def discover() -> int:
    """Scan all discovery directories for YAML config snippets.

    Each YAML file must have a top-level key matching a registered
    section name::

        # config/discovery/build_detectors.yaml
        build_detectors:
          go: {cmd: ["go", "build"]}
          cmake: {cmd: ["cmake", "--build", "."]}

    Returns the number of files loaded.
    """
    import yaml
    loaded = 0
    for d in _DISCOVERY_DIRS:
        base = Path(d)
        if not base.is_dir():
            continue
        for fpath in sorted(base.glob("*.yaml")):
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                for section, values in data.items():
                    if section in _sources:
                        base_dict = _registry.setdefault(section, {})
                        if isinstance(values, dict) and isinstance(base_dict, dict):
                            base_dict.update(values)
                        else:
                            _registry[section] = values
                        logger.info("discovery: %s ← %s (%d keys)", section, fpath.name,
                                    len(values) if isinstance(values, dict) else 1)
                    else:
                        # Unregistered section — silently dropped before this
                        # fix. Warn so dead YAML config is discoverable.
                        logger.warning(
                            "discovery: %s has unregistered section '%s' — ignored "
                            "(register it in boot._init_discovery or remove from YAML)",
                            fpath.name, section,
                        )
                loaded += 1
            except Exception as e:
                logger.warning("discovery: skip %s: %s", fpath.name, e)
    return loaded


def get_config(name: str, default: Any = None) -> Any:
    """Get merged config for a section."""
    return _registry.get(name, default)


def get_tool_config(key: str, default: Any) -> Any:
    """Read a tool config value with params fallback.

    Usage::
        timeout = get_tool_config("git_timeout", TOOL_GIT_TIMEOUT)

    The config layer (praxis.yaml → discovery) is consulted first;
    if unavailable, the params-derived default is returned.
    """
    cfg = get_config("tool")
    if cfg and isinstance(cfg, dict) and key in cfg:
        return cfg[key]
    return default


def get_source(name: str, default: Any = None) -> Any:
    """Get the originally registered defaults (before YAML merge)."""
    return _sources.get(name, default)


def set_config(name: str, key: str, value: Any) -> None:
    """Set a runtime override for a config key."""
    _registry.setdefault(name, {})[key] = value


def reset() -> None:
    """Reset registry to defaults (for testing)."""
    _registry.clear()
    _registry.update({
        k: dict(v) if isinstance(v, dict) else v
        for k, v in _sources.items()
    })


# ── Declarative registration helpers ──────────────────────────────


def register_from_params(params_module: object, section_map: dict[str, str]) -> None:
    """Register config sections from a params module using a mapping.

    Args:
        params_module: A Python module with constant attributes.
        section_map: ``{section_name: [attr_names...]}`` mapping.

    Example::

        register_from_params(params.tool, {
            "danger_levels": ["TOOL_DANGER_LEVEL", "DANGER_TO_GATES"],
            "build_detectors": ["BUILD_DETECTORS", "TEST_DETECTORS"],
        })
    """
    for section, attrs in section_map.items():
        data = {}
        for attr in attrs:
            val = getattr(params_module, attr, None)
            if val is not None:
                data[attr] = val
        if data:
            register(section, data)
