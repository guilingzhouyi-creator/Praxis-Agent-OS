"""YAML config loader — reads praxis.yaml and applies to system settings.

Config precedence (lowest to highest):
  1. kernel/params.py defaults
  2. .praxis_settings.json (user runtime overrides)
  3. praxis.yaml (project configuration file)
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from typing import Any

from .config_handlers import (
    cfg_agent_priority,
    cfg_agent_role_map,
    cfg_agents,
    cfg_api,
    cfg_api_routes,
    cfg_cache,
    cfg_card_gate,
    cfg_card_pool,
    cfg_card_types,
    cfg_cell,
    cfg_clearance,
    cfg_commands,
    cfg_constitution,
    cfg_content_trust,
    cfg_credentials,
    cfg_devices,
    cfg_diff,
    cfg_gatechain,
    cfg_htn,
    cfg_kernel,
    cfg_l3a,
    cfg_language,
    cfg_llm,
    cfg_loop_control,
    cfg_mcp,
    cfg_model_spec,
    cfg_network,
    cfg_persist,
    cfg_persistence,
    cfg_prompts,
    cfg_services,
    cfg_skill,
    cfg_territories,
    cfg_think,
    cfg_tool,
    cfg_tool_rates,
)

logger = logging.getLogger(__name__)

# ── Config handler registry ──

_CONFIG_HANDLERS: dict[str, Callable[[dict, Any, dict], None]] = {}


def register_config_handler(section: str, handler: Callable,
                            override: bool = False) -> None:
    """Register a config section handler.

    The handler receives (section_data, settings, results) and mutates
    results as needed.  Called by apply() for each matching YAML key.
    """
    if section in _CONFIG_HANDLERS and not override:
        raise ValueError(f"config handler '{section}' already registered")
    _CONFIG_HANDLERS[section] = handler


def list_config_handlers() -> list[str]:
    return sorted(_CONFIG_HANDLERS.keys())

def _discover_config_files() -> list[str]:
    """Get config file search paths. Override via env var PRAXIS_CONFIG_PATH."""
    env_path = os.environ.get("PRAXIS_CONFIG_PATH", "")
    if env_path:
        return [env_path]
    from l1.kernel.paths import get_paths

    candidates = [get_paths().config_file, "praxis.yaml", "praxis.yml", ".praxis.yaml", "config/praxis.yaml"]
    return list(dict.fromkeys(candidates))


_CONFIG_FILES = _discover_config_files()


def load_dotenv(path: str = ".env") -> None:
    """Load .env file into os.environ if it exists."""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key and not os.environ.get(key):
                    os.environ[key] = val
    except Exception as e:
            logger.warning("services/config_loader: %s", e)


def _interpolate_env(value: Any) -> Any:
    """Replace ${VAR} references with environment variable values."""
    if isinstance(value, str):
        def _replace(m):
            return os.environ.get(m.group(1), "")
        return re.sub(r"\$\{(\w+)\}", _replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


def find_config(path: str = "") -> str | None:
    """Find the first existing praxis config file."""
    search_paths = [path] if path else _discover_config_files()
    for p in search_paths:
        if os.path.exists(p):
            return p
    # Also search parent directories
    cwd = os.getcwd()
    for part in cwd.split(os.sep):
        parent = os.path.join(*cwd.split(os.sep)[:cwd.split(os.sep).index(part) + 1]) if part else ""
        for fname in _CONFIG_FILES:
            fp = os.path.join(parent, fname) if parent else ""
            if fp and os.path.exists(fp):
                return fp
    return None


def load(config_path: str | None = None) -> dict:
    """Load praxis.yaml and return parsed config dict."""
    try:
        import yaml
    except ImportError:
        return {"success": False, "error": "PyYAML not installed (pip install pyyaml)"}

    path = config_path or find_config()
    if not path or not os.path.exists(path):
        return {"success": False, "error": "no config file found"}

    try:
        load_dotenv()
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data = _interpolate_env(data or {})
        return {"success": True, "path": path, "data": data or {}}
    except Exception as e:
        return {"success": False, "error": f"parse error: {e}"}


def apply(data: dict) -> dict:
    """Apply parsed YAML config to system settings and kernel params.

    Each config section (e.g. ``kernel``, ``llm``) is handled by a
    registered handler.  Extend with ``register_config_handler()``.

    Returns ``{"success": True, "applied": <handler results>, "flat": <flattened>}``
    where ``flat`` is the real flattened config (dotted keys) — the L2 layer
    of SettingsCenter must be loaded from ``flat``, NOT from ``applied``
    (which only holds per-section handler result flags).
    """
    from l1.kernel.settings import get_settings
    from l3.config.settings_center import SettingsCenter as _SC

    if not data:
        return {"success": False, "error": "empty config"}

    s = get_settings()
    results: dict[str, Any] = {}

    for section, handler in _CONFIG_HANDLERS.items():
        section_data = data.get(section)
        if section_data is not None:
            handler(section_data, s, results)

    logger.info("config applied: %s", results)
    flat = _SC._flatten(data)
    return {"success": True, "applied": results, "flat": flat}


# ── Register built-in handlers (imported from config_handlers.py) ──
_builtin_handlers = [
    ("kernel", cfg_kernel), ("cell", cfg_cell), ("llm", cfg_llm),
    ("constitution", cfg_constitution), ("gatechain", cfg_gatechain),
    ("tool_rates", cfg_tool_rates), ("tool", cfg_tool),
    ("htn", cfg_htn),
    ("cache", cfg_cache), ("persist", cfg_persist), ("persistence", cfg_persistence),
    ("network", cfg_network), ("api", cfg_api),
    ("api_routes", cfg_api_routes), ("prompts", cfg_prompts),
    ("credentials", cfg_credentials), ("card_gate", cfg_card_gate), ("card_types", cfg_card_types), ("content_trust", cfg_content_trust), ("commands", cfg_commands), ("mcp", cfg_mcp),
    ("devices", cfg_devices), ("territories", cfg_territories),
    ("clearance", cfg_clearance), ("agents", cfg_agents),
    ("agent_role_map", cfg_agent_role_map),
    ("agent_priority", cfg_agent_priority),
    ("model_spec", cfg_model_spec),
    ("think", cfg_think),
    ("loop", cfg_loop_control),
    ("loop_control", cfg_loop_control),
    ("l3a", cfg_l3a),
    ("skill", cfg_skill),
    ("diff", cfg_diff),
    ("services", cfg_services),
    ("card_pool", cfg_card_pool),
    ("language", cfg_language),
]
for _name, _fn in _builtin_handlers:
    register_config_handler(_name, _fn, override=True)


def validate(data: dict) -> dict:
    """Validate parsed YAML config structure. Returns errors list."""
    errors = []
    sections = ("kernel", "cell", "l3a", "llm", "constitution", "gatechain", "tool_rates",
                "tool", "htn", "cache", "persist", "persistence", "services", "network",
                "api", "api_routes", "prompts", "card_gate", "card_types", "credentials",
                "content_trust", "commands", "mcp", "devices", "territories", "clearance",
                "agents", "agent_role_map", "agent_priority", "model_spec", "think",
                "loop", "loop_control", "diff", "card_pool")
    for sec in sections:
        if sec in data and not isinstance(data[sec], (dict, list)):
            errors.append(f"{sec}: expected dict/list")

    llm = data.get("llm", {})
    try:
        from l4.llm.llm import list_providers
        valid_providers = list_providers() or ["mock"]
    except Exception:
        valid_providers = ("mock", "ollama", "openai", "anthropic")
    if llm and "provider" in llm and llm["provider"] not in valid_providers:
        errors.append(f"llm.provider: '{llm['provider']}' not in {valid_providers}")

    # Validate ring range
    for cf in (data.get("clearance", {}).values()):
        if isinstance(cf, int) and (cf < 1 or cf > 3):
            errors.append(f"clearance: ring {cf} out of range [1,3]")

    clearance = data.get("clearance", {})
    for role, ring in clearance.items():
        if not isinstance(ring, int) or ring < 1 or ring > 3:
            errors.append(f"clearance.{role}: ring must be 1-3, got {ring}")

    agents = data.get("agents", {})
    for role, cfg in agents.items():
        if not isinstance(cfg, dict):
            errors.append(f"agents.{role}: expected dict")
        elif "max_scouts" in cfg and (not isinstance(cfg["max_scouts"], int) or cfg["max_scouts"] < 0):
            errors.append(f"agents.{role}.max_scouts: must be >= 0")

    return {"success": len(errors) == 0, "errors": errors, "count": len(errors)}


def load_and_apply(path: str | None = None) -> dict:
    """Load praxis.yaml and apply all settings. One-shot."""
    r = load(path)
    if not r.get("success"):
        return r
    # Validate before applying
    v = validate(r.get("data", {}))
    if not v["success"]:
        return {"success": False, "error": "config validation failed", "errors": v["errors"]}
    return apply(r.get("data", {}))


def dump_config() -> dict:
    """Dump current effective configuration (from kernel.settings)."""
    try:
        from l1.kernel.settings import get_settings
        s = get_settings()
        return {"success": True, "config": s.all(), "count": len(s.all())}
    except Exception as e:
        return {"success": False, "error": str(e)}


def config_category(prefix: str) -> dict:
    """Get config values for a specific category prefix."""
    try:
        from l1.kernel.settings import get_settings
        s = get_settings()
        return {"success": True, "category": prefix, "values": s.category(prefix),
                "count": len(s.category(prefix))}
    except Exception as e:
        return {"success": False, "error": str(e)}


def watch_config(interval: float = 30.0, callback: callable | None = None) -> dict:
    """Start watching config file for changes. Calls callback on change."""
    import threading
    import time
    path = find_config()
    if not path:
        return {"success": False, "error": "no config file found"}

    last_mtime = os.path.getmtime(path)

    def _watcher():
        nonlocal last_mtime
        while True:
            time.sleep(interval)
            try:
                mtime = os.path.getmtime(path)
                if mtime > last_mtime:
                    last_mtime = mtime
                    r = load_and_apply(path)
                    if callback:
                        callback(r)
            except Exception as e:
                logger.warning("config loader: %s", e)

    t = threading.Thread(target=_watcher, daemon=True)
    t.start()
    return {"success": True, "path": path, "interval": interval}
