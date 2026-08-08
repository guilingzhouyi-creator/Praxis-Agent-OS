"""API handler mixin — route manifest and V1 tools / locale endpoints.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def list_endpoints(routes: list) -> dict:
    """Render the route table + manifest summary."""
    lines = []
    for r in routes:
        display = r.path + "<id>" if r.path.endswith("/") else r.path
        lines.append(f"{r.method:4s} {display:30s}  {r.description}")
    result: dict = {"endpoints": lines}
    # centralized manifest summary (see l4/api/api_endpoints.py)
    try:
        from l4.api.api_endpoints import summary, validate

        result["manifest"] = summary()
        result["manifest_ok"] = validate()["ok"]
    except Exception:
        logger.debug("list_endpoints: manifest summary failed, omitted", exc_info=True)
    return result


def endpoints_only(routes: list) -> list[str]:
    """Return just the endpoint lines."""
    return list_endpoints(routes).get("endpoints", [])


def list_tools_v1(body: dict | None = None) -> dict:
    """Legacy V1 tool listing with locale support."""
    try:
        from l3.tool_system.tool_spec import list_tools

        locale = (body or {}).get("locale", "") if body else ""
        tools = list_tools(locale=locale)
        return {
            "success": True,
            "data": [
                {
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "ring": t.ring,
                    "danger": t.danger,
                    "parameters": [
                        {"name": p.name, "type": p.type, "required": p.required, "description": p.description}
                        for p in t.parameters
                    ],
                }
                for t in tools
            ],
            "count": len(tools),
            "locale": locale or "en",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_locales(body: dict | None = None) -> dict:
    """List available i18n locales + current one."""
    try:
        from l2.i18n import get_available_locales, get_locale

        return {"success": True, "locales": get_available_locales(), "current": get_locale()}
    except Exception as e:
        return {"success": False, "error": str(e)}
