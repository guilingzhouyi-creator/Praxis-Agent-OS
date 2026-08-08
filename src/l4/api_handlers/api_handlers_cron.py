"""API handler mixin — cron scheduler handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def cron_list(body: dict | None = None) -> dict:
    """List cron schedules."""
    try:
        from ..cron_scheduler import get_scheduler

        return {"success": True, "schedules": get_scheduler().list()}
    except Exception as e:
        return {"error": str(e)}


def cron_add(body: dict) -> dict:
    """Add a cron schedule entry."""
    try:
        from ..cron_scheduler import get_scheduler

        entry_id = body.get("id", "")
        cron = body.get("cron", "")
        if not entry_id:
            return {"success": False, "error": "id is required"}
        if not cron:
            return {"success": False, "error": "cron expression is required"}
        return get_scheduler().add(
            entry_id=entry_id,
            cron=cron,
            intent=body.get("intent", ""),
            domain=body.get("domain", ""),
            priority=body.get("priority", 5),
        )
    except Exception as e:
        return {"error": str(e)}


def cron_remove(body: dict) -> dict:
    """Remove a cron schedule entry."""
    try:
        from ..cron_scheduler import get_scheduler

        return get_scheduler().remove(body.get("id", ""))
    except Exception as e:
        return {"error": str(e)}
