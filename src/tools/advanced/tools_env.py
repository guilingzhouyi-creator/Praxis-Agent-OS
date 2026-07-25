"""Environment tools - 5 kinds.

env_list, env_get, env_set, env_unset, path_list
"""

import os
import sys
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R


def _cmd_env_list(args: dict, agent_id: str) -> dict:
    prefix = args.get("prefix", "")
    envs = {}
    for k, v in sorted(os.environ.items()):
        if prefix and not k.startswith(prefix):
            continue
        if not k.startswith("_") or args.get("show_all", False):
            envs[k] = v[:128] if len(v) > 128 else v
    return {"success": True, "data": {"variables": envs, "count": len(envs)}}


def _cmd_env_get(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    if not key:
        return {"success": False, "error": "key is required"}
    value = os.environ.get(key, "")
    return {"success": True, "data": {"key": key, "value": value, "found": bool(value)}}


def _cmd_env_set(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    value = args.get("value", "")
    if not key:
        return {"success": False, "error": "key is required"}
    os.environ[key] = value
    return {"success": True, "data": {"key": key, "value": value, "set": True}}


def _cmd_env_unset(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    if not key:
        return {"success": False, "error": "key is required"}
    os.environ.pop(key, None)
    return {"success": True, "data": {"key": key, "unset": True}}


def _cmd_path_list(args: dict, agent_id: str) -> dict:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    return {"success": True, "data": {"paths": paths, "count": len(paths), "separator": os.pathsep}}


def register_tools() -> None:
    register(ToolSpec(name="env_list", description="List environment variables", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("prefix", "string", default="", description="Filter by variable name prefix"),
                                  ParamSpec("show_all", "bool", default=False, description="Show underscore-prefixed variables")],
                      handler=_cmd_env_list))
    register(ToolSpec(name="env_get", description="Get environment variable value", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("key", "string", required=True)],
                      handler=_cmd_env_get))
    register(ToolSpec(name="env_set", description="Set environment variable (current process only)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("key", "string", required=True), ParamSpec("value", "string", default="")],
                      handler=_cmd_env_set))
    register(ToolSpec(name="env_unset", description="Delete environment variable", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("key", "string", required=True)],
                      handler=_cmd_env_unset))
    register(ToolSpec(name="path_list", description="List PATH directories", category="generic", ring=R.RING_1, danger=0,
                      handler=_cmd_path_list))