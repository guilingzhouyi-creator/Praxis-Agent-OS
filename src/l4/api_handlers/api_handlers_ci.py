"""API handlers for /api/v2/ci/* endpoints (card-triggered CI review).

Exposes review reports and the runtime review switch.  Read-only queries
plus a single toggle — manual re-runs / gate editing are out of scope.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.system import CI_DEFAULT_LIST_LIMIT

logger = logging.getLogger(__name__)


def handle_ci_reviews(body: dict | None = None) -> dict:
    """GET /api/v2/ci/reviews — query review reports."""
    b = body or {}
    try:
        from l4.ci_review import get_service
        return get_service().query(
            card_id=str(b.get("card_id", "")),
            status=str(b.get("status", "")),
            limit=int(b.get("limit", CI_DEFAULT_LIST_LIMIT)),
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_ci_review_get(body: dict | None = None, card_id: str = "") -> dict:
    """GET /api/v2/ci/reviews/{card_id} — single card latest report."""
    try:
        from l4.ci_review import get_service
        result = get_service().query(card_id=card_id, limit=1)
        reports = result.get("reports", [])
        if not reports:
            return {"success": False, "error": f"no CI review found for card: {card_id}"}
        return {"success": True, "report": reports[0]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _resolve_key(key: str) -> str:
    """Map a short alias (e.g. ``enabled``) to its full ``ci.review.*`` key."""
    return key if key.startswith("ci.") else f"ci.review.{key}"


def handle_ci_config_get(body: dict | None = None) -> dict:
    """GET /api/v2/ci/config — full review switch state + surface permissions."""
    try:
        from l3.config.settings_center import get_center
        from l4.ci_review import CI_SETTING_KEYS, get_service

        center = get_center()
        svc = get_service()
        return {
            "success": True,
            "settings": {key: center.get(key) for key in sorted(CI_SETTING_KEYS)},
            "control": {
                "api": {"writable": svc._surface_writable("api")},
                "shell": {"writable": svc._surface_writable("shell")},
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_ci_config_set(body: dict | None = None) -> dict:
    """PUT /api/v2/ci/config — update review switches (whitelisted keys only).

    Accepts either direct key/value pairs (``{"enabled": false}``) or an
    explicit ``{"key": "...", "value": ...}`` form.  Writes are gated by
    ``ci.control.api.writable``; keys outside ``CI_SETTING_KEYS`` are
    rejected (control-plane keys cannot be self-elevated).
    """
    b = body or {}
    try:
        from l3.config.settings_center import get_center
        from l4.ci_review import CI_SETTING_KEYS, get_service

        center = get_center()
        svc = get_service()
        if not svc._surface_writable("api"):
            return {"success": False,
                    "error": "writes disabled (ci.control.api.writable=false)"}
        updates: dict[str, Any] = {}
        if "key" in b:
            updates[_resolve_key(str(b["key"]))] = b.get("value")
        else:
            for key, value in b.items():
                if key in ("key", "value"):
                    continue
                updates[_resolve_key(key)] = value
        rejected = [k for k in updates if k not in CI_SETTING_KEYS]
        if rejected:
            return {"success": False, "error": f"keys not writable: {rejected}",
                    "allowed": sorted(CI_SETTING_KEYS)}
        if not updates:
            return {"success": False, "error": "no writable keys provided"}
        for key, value in updates.items():
            center.set(key, value)
        return {"success": True, "updated": updates}
    except Exception as e:
        return {"success": False, "error": str(e)}
