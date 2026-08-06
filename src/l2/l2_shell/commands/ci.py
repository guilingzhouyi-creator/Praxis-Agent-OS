"""L2 Shell: card-triggered CI review command (ci)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _parse_value(raw: str):
    """Parse a CLI value into bool / int / list / str."""
    v = raw.strip()
    low = v.lower()
    if low in ("true", "on", "yes", "1"):
        return True
    if low in ("false", "off", "no", "0"):
        return False
    if v.startswith("[") and v.endswith("]"):
        return [i.strip().strip("'\"") for i in v[1:-1].split(",") if i.strip()]
    try:
        return int(v)
    except ValueError:
        return v


def _cmd_ci(args: list[str]) -> dict:
    """Show CI review stats/reports, inspect or set review switches."""
    try:
        from l3.config.settings_center import get_center
        from l4.ci_review import CI_SETTING_KEYS, get_service

        svc = get_service()
        center = get_center()
        if not args:
            return {"success": True, **svc.stats()}
        sub = args[0].lower()
        if sub == "list":
            status = args[1] if len(args) > 1 else ""
            return svc.query(status=status)
        if sub == "show":
            if len(args) < 2:
                return {"success": False, "error": "usage: /ci show <card_id>"}
            return svc.query(card_id=args[1], limit=1)
        if sub == "config":
            return {
                "success": True,
                "settings": {k: center.get(k) for k in sorted(CI_SETTING_KEYS)},
                "control": {
                    "api": {"writable": svc._surface_writable("api")},
                    "shell": {"writable": svc._surface_writable("shell")},
                },
            }
        if sub == "set":
            if len(args) < 3:
                return {"success": False,
                        "error": "usage: /ci set <key> <value> (e.g. /ci set enabled false)"}
            key = args[1]
            full_key = key if key.startswith("ci.") else f"ci.review.{key}"
            if full_key not in CI_SETTING_KEYS:
                return {"success": False, "error": f"key not writable: {full_key}",
                        "allowed": sorted(CI_SETTING_KEYS)}
            if not svc._surface_writable("shell"):
                return {"success": False,
                        "error": "writes disabled (ci.control.shell.writable=false)"}
            value = _parse_value(" ".join(args[2:]))
            center.set(full_key, value)
            return {"success": True, "key": full_key, "value": value}
        if sub == "toggle":
            if not svc._surface_writable("shell"):
                return {"success": False,
                        "error": "writes disabled (ci.control.shell.writable=false)"}
            enabled = not bool(center.get("ci.review.enabled", True))
            center.set("ci.review.enabled", enabled)
            return {"success": True, "enabled": enabled}
        return {"success": False,
                "error": f"unknown ci subcommand: {sub} (expected config|set|list|show|toggle)"}
    except Exception as e:
        return {"success": False, "error": str(e)}
