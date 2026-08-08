"""API handler mixin — loop auto-test and loop-config endpoints.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def loop_auto_test_get(body: dict | None = None) -> dict:
    """GET /api/v2/loop/auto-test — AutoTestGate state + pending feedback."""
    from l3.tool_system.auto_test import auto_test_status

    return {"success": True, **auto_test_status()}


def loop_auto_test_set(body: dict) -> dict:
    """PUT /api/v2/loop/auto-test — switch AutoTestGate mode (off|async)."""
    from l3.tool_system.auto_test import set_auto_test

    return set_auto_test(body.get("mode", ""), source="api")


def loop_config_get(body: dict | None = None) -> dict:
    """Read loop tuning knobs from SettingsCenter."""
    try:
        from l3.config.settings_center import get_center

        center = get_center()
        keys = [
            "loop.max_steps",
            "loop.timeout",
            "loop.max_iterations",
            "loop.max_attempts",
            "loop.continuation_nudge",
            "loop.tool_repeat_warn",
            "loop.tool_repeat_stop",
            "loop.coarse_repeat_nudge",
            "loop.coarse_repeat_stop",
            "loop.verify_cadence",
        ]
        return {"success": True, "config": {k: center.get(k) for k in keys}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def loop_config_set(body: dict) -> dict:
    """Write loop tuning knobs (keys without the ``loop.`` prefix)."""
    try:
        from l3.config.settings_center import get_center

        center = get_center()
        config = body or {}
        applied = []
        for key in config:
            center.set(f"loop.{key}", config[key])
            applied.append(key)
        return {"success": True, "applied": applied}
    except Exception as e:
        return {"success": False, "error": str(e)}
