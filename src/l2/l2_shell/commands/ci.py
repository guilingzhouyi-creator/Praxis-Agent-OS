"""L2 Shell: card-triggered CI review command (ci)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _cmd_ci(args: list[str]) -> dict:
    """Show CI review stats/reports or toggle the review switch."""
    try:
        from l4.ci_review import get_service

        svc = get_service()
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
        if sub == "toggle":
            from l3.config.settings_center import get_center
            enabled = not bool(get_center().get("ci.review.enabled", True))
            get_center().set("ci.review.enabled", enabled)
            return {"success": True, "enabled": enabled}
        return {"success": False,
                "error": f"unknown ci subcommand: {sub} (expected list|show|toggle)"}
    except Exception as e:
        return {"success": False, "error": str(e)}
