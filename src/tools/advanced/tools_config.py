"""Config tools - 5 kinds.

config_get, config_set, config_list, config_reset, secret_read
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

# Simulated config storage
_config_store: dict[str, dict] = {}


def _load_config(path: str) -> dict:
    if path in _config_store:
        return _config_store[path]
    p = Path(path)
    if p.exists():
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
            _config_store[path] = data
            return data
        except Exception as e:
            logger.warning("tools_config: %s", e)
    return {}


def _cmd_config_get(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    path = args.get("path", "config.json")
    if not key:
        return {"success": False, "error": "key is required"}
    config = _load_config(path)
    value = config.get(key)
    return {"success": True, "data": {"key": key, "value": value, "source": path}}


def _cmd_config_set(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    value = args.get("value", "")
    path = args.get("path", "config.json")
    if not key:
        return {"success": False, "error": "key is required"}
    config = _load_config(path)
    config[key] = value
    _config_store[path] = config
    try:
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
            logger.warning("tools_config: %s", e)
    return {"success": True, "data": {"key": key, "value": value, "path": path, "set": True}}


def _cmd_config_list(args: dict, agent_id: str) -> dict:
    path = args.get("path", "config.json")
    config = _load_config(path)
    return {"success": True, "data": {"config": config, "count": len(config), "source": path}}


def _cmd_config_reset(args: dict, agent_id: str) -> dict:
    path = args.get("path", "config.json")
    _config_store.pop(path, None)
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
    except Exception as e:
            logger.warning("tools_config: %s", e)
    return {"success": True, "data": {"path": path, "reset": True}}


def _cmd_secret_read(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    if not key:
        return {"success": False, "error": "key is required"}
    # Read secret from env var (secure)
    value = os.environ.get(key, "")
    if not value:
        try:
            from app.key_vault import get_key_vault
            value = get_key_vault().get(key, "")
        except Exception as e:
            logger.warning("tools_config: %s", e)
    return {"success": True, "data": {"key": key, "found": bool(value), "length": len(value) if value else 0}}


def register_tools() -> None:
    register(ToolSpec(name="config_get", description="Read configuration value", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("key", "string", required=True), ParamSpec("path", "string", default="config.json")],
                      handler=_cmd_config_get))
    register(ToolSpec(name="config_set", description="Set configuration value", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("key", "string", required=True), ParamSpec("value", "string", default=""),
                                  ParamSpec("path", "string", default="config.json")],
                      handler=_cmd_config_set))
    register(ToolSpec(name="config_list", description="List all configuration items", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default="config.json")],
                      handler=_cmd_config_list))
    register(ToolSpec(name="config_reset", description="Reset configuration file", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", default="config.json")],
                      handler=_cmd_config_reset))
    register(ToolSpec(name="secret_read", description="Read secret (from env var or KeyVault)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("key", "string", required=True)],
                      handler=_cmd_secret_read))