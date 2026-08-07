"""Environment tool handlers."""

import os


def env_get(args: dict, agent_id: str) -> dict:
    """Read an environment variable by name; returns value dict."""
    name = args.get("name", "")
    if not name:
        return {"success": False, "error": "name is required"}
    val = os.environ.get(name)
    return {"success": True, "name": name, "value": val}


def env_list(args: dict, agent_id: str) -> dict:
    """List all environment variables sorted by name; returns items dict."""
    items = dict(sorted(os.environ.items()))
    return {"success": True, "items": items, "count": len(items)}


def reset_workspace(args: dict, agent_id: str) -> dict:
    """RING_3: Reset workspace to initial state via factory_reset."""
    from l3.boot.lifecycle import factory_reset

    r = factory_reset(wipe_config=args.get("wipe_config", False))
    return {"success": r.get("success", False), **r}
