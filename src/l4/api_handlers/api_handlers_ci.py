"""API handlers for /api/v2/ci/* endpoints (card-triggered CI review).

Exposes review reports and the runtime review switch.  Read-only queries
plus a single toggle — manual re-runs / gate editing are out of scope.
"""

from __future__ import annotations

import logging

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


def handle_ci_config_set(body: dict | None = None) -> dict:
    """PUT /api/v2/ci/config — toggle the CI review runtime switch."""
    b = body or {}
    try:
        from l3.config.settings_center import get_center
        key = "ci.review.enabled"
        enabled = bool(b.get("enabled", True))
        get_center().set(key, enabled)
        return {"success": True, "key": key, "enabled": enabled}
    except Exception as e:
        return {"success": False, "error": str(e)}
