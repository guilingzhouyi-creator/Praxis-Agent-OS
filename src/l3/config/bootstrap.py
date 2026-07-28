"""Bootstrap wizard — first-boot configuration generator.

On first launch (no praxis.yaml found), generates configuration
with defaults or user-provided settings. Exposes API for TUI.

API endpoints:
  GET  /api/bootstrap/status — check if bootstrap is needed
  GET  /api/bootstrap/defaults — get default config values
  POST /api/bootstrap/apply  — apply a config dict, write praxis.yaml
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

import yaml

from l1.kernel.params.agent import CENTRAL_DEFAULT_ROLES
from l1.kernel.params.api import (
    API_GATEWAY_HOST, API_GATEWAY_PORT, LLM_PROVIDER_URLS,
    DEFAULT_MODEL_OPENAI, DEFAULT_MODEL_OPENAI_MINI,
    DEFAULT_MODEL_ANTHROPIC_SONNET, DEFAULT_MODEL_ANTHROPIC_HAIKU,
    DEFAULT_MODEL_DEEPSEEK_V4, DEFAULT_MODEL_DEEPSEEK_CHAT,
    DEFAULT_MODEL_OLLAMA, DEFAULT_MODEL_MOCK,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = "config/praxis.yaml"
_BACKUP_SUFFIX = ".bak"

# ── Default configuration template ──

def default_config() -> dict:
    """Return the default configuration dict from kernel/params.py constants."""
    from l1.kernel.params.agent import TERMINAL_MAX_WORKERS, CARD_TIMEOUT
    from l1.kernel.params.api import API_GATEWAY_HOST, API_GATEWAY_PORT
    from l1.kernel.params.kernel import ALLOCATOR_DEFAULTS, SWAPPER_DEFAULT_INTERVAL
    from l1.kernel.params.system import (
        SCOUT_POOL_MAX_PER_AGENT,
        SCOUT_CACHE_TTL,
        SCOUT_POOL_MAX,
        MEMORY_RING_WORKING_BUDGET,
        MEMORY_RING_SHORT_BUDGET,
        MEMORY_RING_LONG_BUDGET,
        MEMORY_RING_WORKING_TTL,
        MEMORY_RING_SHORT_TTL,
        MEMORY_RING_LONG_TTL,
    )
    return {
        "cell": {
            "terminal": {"workers": TERMINAL_MAX_WORKERS, "poll": 0.05},
            "scout": {"max_total": SCOUT_POOL_MAX, "max_per_agent": SCOUT_POOL_MAX_PER_AGENT, "cache_ttl": SCOUT_CACHE_TTL},
            "card": {"timeout": CARD_TIMEOUT},
        },
        "kernel": {
            "allocator": {"tokens": ALLOCATOR_DEFAULTS.tokens},
            "swapper": {"interval": SWAPPER_DEFAULT_INTERVAL},
        },
        "llm": {
            "provider": "<provider>", "model": "<model>", "api_url": "",
            "max_tokens": 4096, "temperature": 0.3,
        },
        "territories": {"reader": ["."], "writer": ["."], "reviewer": ["."]},
        "clearance": {"reader": 1, "writer": 2, "reviewer": 3},
        "agents": {
            "reader": {"max_scouts": 3, "ring": 1},
            "writer": {"max_scouts": 3, "ring": 2},
            "reviewer": {"max_scouts": 1, "ring": 3},
        },
        "api": {"host": API_GATEWAY_HOST, "port": API_GATEWAY_PORT, "auth_token": ""},
    }


# ── Public API (for TUI) ──

def needs_bootstrap() -> bool:
    """Check if first-boot wizard should run (no config file exists)."""
    return not os.path.exists(_CONFIG_PATH)


def get_defaults() -> dict:
    """Return default config values for TUI to pre-fill forms."""
    from l1.kernel.params.system import (
        MEMORY_RING_WORKING_BUDGET,
        MEMORY_RING_SHORT_BUDGET,
        MEMORY_RING_LONG_BUDGET,
        MEMORY_RING_WORKING_TTL,
        MEMORY_RING_SHORT_TTL,
        MEMORY_RING_LONG_TTL,
    )
    cfg = default_config()
    return {
        "cells": 1,
        "agents_per_cell": 3,
        "default_roles": list(CENTRAL_DEFAULT_ROLES),
        "llm_providers": [
            {"name": "openai", "url": "https://api.openai.com/v1", "models": [DEFAULT_MODEL_OPENAI, DEFAULT_MODEL_OPENAI_MINI]},
            {"name": "anthropic", "url": "https://api.anthropic.com/v1", "models": [DEFAULT_MODEL_ANTHROPIC_SONNET, DEFAULT_MODEL_ANTHROPIC_HAIKU]},
            {"name": "deepseek", "url": "https://api.deepseek.com/v1", "models": [DEFAULT_MODEL_DEEPSEEK_V4, DEFAULT_MODEL_DEEPSEEK_CHAT]},
            {"name": "ollama", "url": LLM_PROVIDER_URLS.get("ollama", "http://localhost:11434"), "models": [DEFAULT_MODEL_OLLAMA]},
            {"name": "mock", "url": "", "models": [DEFAULT_MODEL_MOCK]},
        ],
        "token_presets": [
            {"label": f"Small ({MEMORY_RING_WORKING_BUDGET//1024}K/{MEMORY_RING_SHORT_BUDGET//1024}K/{MEMORY_RING_LONG_BUDGET//1024}K)",
             "working": MEMORY_RING_WORKING_BUDGET, "short": MEMORY_RING_SHORT_BUDGET, "long": MEMORY_RING_LONG_BUDGET},
            {"label": "Medium (16K/64K/256K)", "working": 16384, "short": 65536, "long": 262144},
            {"label": "Large (32K/128K/512K)", "working": 32768, "short": 131072, "long": 524288},
        ],
        "memory_ring_ttl": {
            "ring1": int(MEMORY_RING_WORKING_TTL), "ring2": int(MEMORY_RING_SHORT_TTL), "ring3": int(MEMORY_RING_LONG_TTL),
        },
        "config": cfg,
    }


def apply_config(config: dict) -> dict:
    """Apply a user-provided config dict. Writes to praxis.yaml.

    Args:
        config: Full config dict with sections:
            {territories, clearance, agents, llm, api, ...}

    Returns:
        {"success": bool, "config_path": str, "cells": int, "agents": int}
    """
    num_cells = config.pop("_cells", 1)
    validate_errors = _validate(config)
    if validate_errors:
        return {"success": False, "error": "; ".join(validate_errors)}

    # Merge with defaults for missing sections
    merged = default_config()
    merged.update(config)
    if "api" in config:
        merged["api"] = {**merged["api"], **config["api"]}

    result = _write_config(merged, num_cells)
    return result


# ── Interactive CLI wizard (legacy, for terminal use) ──

def run_bootstrap(interactive: bool = True) -> dict:
    """Run the bootstrap wizard (CLI or auto)."""
    if not interactive:
        return apply_config(default_config())

    print("=" * 60)
    print("  Praxis Agent OS — First Boot Configuration")
    print("=" * 60)
    print()

    config: dict[str, Any] = {}
    num_cells = _prompt_int("  Number of Cells", default=1, min_val=1, max_val=8)
    agents_per_cell = _prompt_int("  Agents per Cell", default=3, min_val=1, max_val=16)
    print()
    default_roles = list(CENTRAL_DEFAULT_ROLES)
    agents_config = []
    for i in range(agents_per_cell):
        role = default_roles[i] if i < len(default_roles) else f"agent-{chr(97+i)}"
        r = _prompt_string(f"  Agent {i+1} role", default=role)
        agents_config.append(r)

    config["territories"] = {r: [_prompt_string(f"  Territory for '{r}'", default=".")] for r in agents_config}
    config["clearance"] = {r: (1 if r in ("reader", "scout") else 2) for r in agents_config}
    config["agents"] = {r: {"max_scouts": 3, "ring": config["clearance"][r]} for r in agents_config}
    config["_cells"] = num_cells

    print()
    config["kernel"] = {"allocator": {"tokens": _prompt_int("  Max tokens", default=131072)}, "swapper": {"interval": 60.0}}
    config["llm"] = {
        "provider": _prompt_string("  LLM Provider", default="openai"),
        "model": _prompt_string("  Model", default="gpt-4o"),
        "api_url": _prompt_string("  API URL", default="https://api.openai.com/v1"),
        "max_tokens": _prompt_int("  Max output tokens", default=4096),
        "temperature": 0.3,
    }
    api_key = _prompt_string("  API Key (blank = env var)", default="")
    if api_key:
        config["credentials"] = {config["llm"]["provider"]: {"api_key": api_key}}

    enable_api = _prompt_bool("  Enable HTTP API", default=True)
    if enable_api:
        config["api"] = {
            "host": API_GATEWAY_HOST,
            "port": _prompt_int("  Port", default=API_GATEWAY_PORT),
            "auth_token": _prompt_string("  Auth token", default=""),
        }

    print()
    result = apply_config(config)
    if result.get("success"):
        print(f"\n  Config written to {_CONFIG_PATH}")

    return result


# ── Internal ──


def _validate(config: dict) -> list[str]:
    errors = []
    llm = config.get("llm", {})
    if llm.get("provider") and llm.get("provider") not in ("mock", "openai", "anthropic", "deepseek", "ollama"):
        errors.append(f"unknown provider: {llm['provider']}")
    for section in ("territories", "clearance"):
        if section in config and not isinstance(config[section], dict):
            errors.append(f"{section}: expected dict")
    return errors


def _write_config(config: dict, num_cells: int = 1) -> dict:
    if os.path.exists(_CONFIG_PATH):
        shutil.copy2(_CONFIG_PATH, _CONFIG_PATH + _BACKUP_SUFFIX)
    try:
        with open(_CONFIG_PATH + ".tmp", "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True, indent=2)
        os.replace(_CONFIG_PATH + ".tmp", _CONFIG_PATH)
        logger.info("bootstrap config written: %d cells", num_cells)
        return {"success": True, "config_path": _CONFIG_PATH, "cells": num_cells,
                "agents": len(config.get("agents", {}))}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _prompt_int(prompt, default, min_val=1, max_val=65535):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"  Value must be between {min_val} and {max_val}.")
        except ValueError:
            print("  Please enter a number.")


def _prompt_string(prompt, default=""):
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else default


def _prompt_bool(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "true", "1")
    """Generate a minimal default config without user interaction."""
    config = {
        "kernel": {"allocator": {"tokens": 131072}, "swapper": {"interval": 60.0}},
        "cell": {
            "terminal": {"workers": 4, "poll": 0.05},
            "scout": {"max_total": 16, "max_per_agent": 4, "cache_ttl": 30.0},
            "card": {"timeout": 30.0},
        },
        "llm": {
            "provider": "mock",
            "model": "mock",
            "api_url": "",
            "max_tokens": 4096,
            "temperature": 0.3,
        },
        "territories": {"reader": ["."], "writer": ["."], "reviewer": ["."]},
        "clearance": {"reader": 1, "writer": 2, "reviewer": 3},
        "agents": {
            "reader": {"max_scouts": 3, "ring": 1},
            "writer": {"max_scouts": 3, "ring": 2},
            "reviewer": {"max_scouts": 3, "ring": 3},
        },
        "api": {"host": API_GATEWAY_HOST, "port": API_GATEWAY_PORT, "auth_token": ""},
    }
    result = _write_config(config, 1)
    if result.get("success"):
        logger.info("default config written to %s", _CONFIG_PATH)
    return result


def _prompt_int(prompt: str, default: int, min_val: int = 1,
                max_val: int = 65535) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"  Value must be between {min_val} and {max_val}.")
        except ValueError:
            print("  Please enter a number.")


def _prompt_string(prompt: str, default: str = "") -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else default


def _prompt_bool(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "true", "1")


def _write_config(config: dict, num_cells: int) -> dict:
    """Write config to praxis.yaml with backup of existing file."""
    if os.path.exists(_CONFIG_PATH):
        backup = _CONFIG_PATH + _BACKUP_SUFFIX
        shutil.copy2(_CONFIG_PATH, backup)
        logger.info("existing config backed up to %s", backup)

    try:
        with open(_CONFIG_PATH + ".tmp", "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True, indent=2)
        os.replace(_CONFIG_PATH + ".tmp", _CONFIG_PATH)
        logger.info("bootstrap config written: %d cells, %s", num_cells, _CONFIG_PATH)
        return {
            "success": True,
            "config_path": _CONFIG_PATH,
            "cells": num_cells,
            "agents": len(config.get("agents", {})),
        }
    except Exception as e:
        logger.error("bootstrap write failed: %s", e)
        return {"success": False, "error": str(e)}
