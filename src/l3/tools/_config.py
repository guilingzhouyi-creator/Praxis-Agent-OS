"""Config tool handlers."""

import logging

logger = logging.getLogger(__name__)

try:
    from l3.config.settings_center import get_center
    HAS_SETTINGS = True
except ImportError:
    HAS_SETTINGS = False


def config_get(args: dict, agent_id: str) -> dict:
    """Read a config value by key from the settings center; returns value dict."""
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
    """Write a config value by key to the settings center; returns value dict."""
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
    """List all config items from the settings center; returns items dict."""
    if not HAS_SETTINGS:
        return {"success": False, "error": "settings not available"}
    try:
        items = get_center().all()
        return {"success": True, "items": items, "count": len(items)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def clear_caches(args: dict, agent_id: str) -> dict:
    """RING_3: Flush all runtime caches."""
    flushed = []
    try:
        from l3.memory.cache import reset_caches
        reset_caches()
        flushed.append("memory_cache")
    except Exception:
        logger.debug("_config: memory cache reset failed")
    try:
        from l3.cell import get_cells
        for cell in get_cells().values():
            cache = getattr(cell, 'cache', None)
            if cache:
                cache.clear()
            icache = getattr(cell, 'icache', None)
            if icache:
                icache.clear()
        flushed.append("cell_caches")
    except Exception:
        logger.debug("_config: cell caches clear failed")
    try:
        from l3.tool_system.tool_registry import clear_mutes
        clear_mutes()
        flushed.append("tool_mutes")
    except Exception:
        logger.debug("_config: tool mutes clear failed")
    return {"success": True, "flushed": flushed}
