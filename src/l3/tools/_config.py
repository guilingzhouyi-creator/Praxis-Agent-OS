"""Config tool handlers."""

try:
    from l3.config.settings_center import get_center
    HAS_SETTINGS = True
except ImportError:
    HAS_SETTINGS = False


def config_get(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    if not key:
        return {"success": False, "error": "key is required"}
    if not HAS_SETTINGS:
        return {"success": False, "error": "settings not available"}
    try:
        val = get_center().get(key)
        return {"success": True, "key": key, "value": val}
    except Exception as e:
        return {"success": False, "error": str(e)}


def config_set(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    value = args.get("value", "")
    if not key:
        return {"success": False, "error": "key is required"}
    if not HAS_SETTINGS:
        return {"success": False, "error": "settings not available"}
    try:
        get_center().set(key, value)
        return {"success": True, "key": key, "value": value}
    except Exception as e:
        return {"success": False, "error": str(e)}


def config_list(args: dict, agent_id: str) -> dict:
    if not HAS_SETTINGS:
        return {"success": False, "error": "settings not available"}
    try:
        items = get_center().all()
        return {"success": True, "items": items, "count": len(items)}
    except Exception as e:
        return {"success": False, "error": str(e)}
