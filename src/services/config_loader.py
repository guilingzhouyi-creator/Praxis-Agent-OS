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
from pathlib import Path
from typing import Any, Callable

from kernel.params import (
    TERRITORY_MAP, TERRITORY_PATHS, SHARED_PATHS,
    DEFAULT_AGENT_CONFIGS, AGENT_CLEARANCE,
    ALLOCATOR_DEFAULTS, SCOUT_POOL_MAX_TOTAL, SCOUT_POOL_MAX_PER_AGENT,
    SCOUT_CACHE_TTL, TERMINAL_MAX_WORKERS, TERMINAL_POLL_INTERVAL,
    CARD_WAIT_TIMEOUT,
)
from kernel.device import get_device_manager, DeviceType
from .config_handlers import (
    cfg_kernel, cfg_cell, cfg_llm, cfg_constitution, cfg_gatechain,
    cfg_tool_rates, cfg_htn, cfg_cache, cfg_persist, cfg_network,
    cfg_api, cfg_api_routes, cfg_prompts, cfg_credentials, cfg_card_gate, cfg_card_types, cfg_content_trust, cfg_commands, cfg_mcp,
    cfg_devices, cfg_territories, cfg_clearance, cfg_agents,
)

logger = logging.getLogger(__name__)

# ── Config handler registry ──

_CONFIG_HANDLERS: dict[str, Callable[[dict, "Any", dict], None]] = {}


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

_CONFIG_FILES = [
    "praxis.yaml",
    "praxis.yml",
    ".praxis.yaml",
    "config/praxis.yaml",
]


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
    search_paths = [path] if path else _CONFIG_FILES
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
    """
    from kernel.settings import get_settings

    if not data:
        return {"success": False, "error": "empty config"}

    s = get_settings()
    results: dict[str, Any] = {}

    for section, handler in _CONFIG_HANDLERS.items():
        section_data = data.get(section)
        if section_data is not None:
            handler(section_data, s, results)

    # devices / territories / clearance / agents — not keyed by section name
    for section in ("devices", "territories", "clearance", "agents"):
        handler = _CONFIG_HANDLERS.get(section)
        if handler and section in data:
            handler(data.get(section, {}), s, results)

    logger.info("config applied: %s", results)
    return {"success": True, "applied": results}


# ── Register built-in handlers (imported from config_handlers.py) ──
_builtin_handlers = [
    ("kernel", cfg_kernel), ("cell", cfg_cell), ("llm", cfg_llm),
    ("constitution", cfg_constitution), ("gatechain", cfg_gatechain),
    ("tool_rates", cfg_tool_rates), ("htn", cfg_htn),
    ("cache", cfg_cache), ("persist", cfg_persist),
    ("network", cfg_network), ("api", cfg_api),
    ("api_routes", cfg_api_routes), ("prompts", cfg_prompts),
    ("credentials", cfg_credentials), ("card_gate", cfg_card_gate), ("card_types", cfg_card_types), ("content_trust", cfg_content_trust), ("commands", cfg_commands), ("mcp", cfg_mcp),
    ("devices", cfg_devices), ("territories", cfg_territories),
    ("clearance", cfg_clearance), ("agents", cfg_agents),
]
for _name, _fn in _builtin_handlers:
    register_config_handler(_name, _fn, override=True)


def validate(data: dict) -> dict:
    """Validate parsed YAML config structure. Returns errors list."""
    errors = []
    sections = ("kernel", "cell", "llm", "constitution", "gatechain", "tool_rates",
                "htn", "cache", "persist", "network", "api", "api_routes",
                "prompts", "card_gate", "credentials",
                "devices", "territories", "clearance", "agents")
    for sec in sections:
        if sec in data and not isinstance(data[sec], (dict, list)):
            errors.append(f"{sec}: expected dict/list")

    llm = data.get("llm", {})
    try:
        from .llm import list_providers
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
        from kernel.settings import get_settings
        s = get_settings()
        return {"success": True, "config": s.all(), "count": len(s.all())}
    except Exception as e:
        return {"success": False, "error": str(e)}


def config_category(prefix: str) -> dict:
    """Get config values for a specific category prefix."""
    try:
        from kernel.settings import get_settings
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
