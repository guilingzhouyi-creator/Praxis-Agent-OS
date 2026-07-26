"""Environment tool handlers."""

import os


def env_get(args: dict, agent_id: str) -> dict:
    name = args.get("name", "")
    if not name:
        return {"success": False, "error": "name is required"}
    val = os.environ.get(name)
    return {"success": True, "name": name, "value": val}


def env_list(args: dict, agent_id: str) -> dict:
    items = dict(sorted(os.environ.items()))
    return {"success": True, "items": items, "count": len(items)}
