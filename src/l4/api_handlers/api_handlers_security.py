"""API handler mixin — security check / stats and posture-mode handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def security_check(body: dict) -> dict:
    """Run a full security check for an action."""
    from l3.services.central_security import get_center

    return get_center().check_all(
        action=body.get("action", ""),
        agent_id=body.get("agent_id", ""),
        target=body.get("target", ""),
        args=body.get("args", {}),
        tool_name=body.get("tool_name", ""),
        user_token=body.get("user_token", ""),
    )


def security_stats(body: dict | None = None) -> dict:
    """Central security statistics."""
    from l3.services.central_security import get_center

    return get_center().stats()


def security_mode_get(body: dict | None = None) -> dict:
    """System security-posture status."""
    from l3.tool_system.security_mode import security_status

    return security_status()


def security_mode_set(body: dict) -> dict:
    """Switch security posture (productive | security-test)."""
    from l3.tool_system.security_mode import set_security_mode

    return set_security_mode(
        body.get("mode", ""),
        confirmed=bool(body.get("confirm_risk")),
        source="api",
    )


def security_mode_notifications(body: dict | None = None) -> dict:
    """Recent bypass-detection warnings + mode changes (pull channel)."""
    from l3.tool_system.security_mode import security_notifications

    b = body or {}
    try:
        limit = int(b.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0
    event_type = str(b.get("event_type", ""))
    items = security_notifications(limit=limit, event_type=event_type)
    return {"success": True, "count": len(items), "notifications": items}


def security_alerts(body: dict | None = None) -> dict:
    """Danger-action broadcasts (auto-approved / blocked high-danger calls, pull channel)."""
    from l1.kernel.notify import get_notify

    b = body or {}
    try:
        limit = int(b.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0
    items = get_notify().recent(limit=limit)
    return {"success": True, "count": len(items), "alerts": items}


def tool_mode_get(body: dict | None = None) -> dict:
    """Current tool mode."""
    from l3.tool_system.tool_mode import get_mode

    return {"mode": get_mode()}


def tool_mode_set(body: dict) -> dict:
    """Toggle / set tool mode."""
    from l3.tool_system.tool_mode import set_mode

    return set_mode(body.get("mode", "toggle"))


def harness_mode_get(body: dict | None = None) -> dict:
    """Harness mode status."""
    from l3.tool_system.harness import harness_status

    return harness_status()


def harness_mode_set(body: dict) -> dict:
    """Set harness mode with risk confirmation."""
    from l3.tool_system.harness import set_harness_mode

    return set_harness_mode(body.get("mode", ""), confirmed=bool(body.get("confirm_risk")), source="api")
