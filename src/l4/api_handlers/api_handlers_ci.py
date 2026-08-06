"""API handlers for /api/v2/ci/* endpoints (card-triggered CI review).

Exposes review reports and fine-grained control of the review switches:
functional sub-keys (global or per cell/agent scope) plus control-plane
write permissions (requiring admin confirmation).
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


def handle_ci_review_rerun(body: dict | None = None, card_id: str = "") -> dict:
    """POST /api/v2/ci/reviews/{card_id}/rerun — re-run the review for a card."""
    try:
        from l4.ci_review import get_service

        svc = get_service()
        if not svc._surface_writable("api"):
            return {"success": False,
                    "error": "writes disabled (ci.control.api.writable=false)"}
        return svc.rerun(card_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


def _scope_from_body(body: dict) -> tuple[str, str]:
    """Extract (cell_id, agent_id) scope selectors from a request body."""
    scope = body.get("scope")
    cell_id = str(scope.get("cell", "")) if isinstance(scope, dict) else ""
    agent_id = str(scope.get("agent", "")) if isinstance(scope, dict) else ""
    return cell_id or str(body.get("cell_id", "")), agent_id or str(body.get("agent_id", ""))


def handle_ci_config_get(body: dict | None = None) -> dict:
    """GET /api/v2/ci/config — switch state, scoped effective values, permissions."""
    b = body or {}
    cell_id, agent_id = _scope_from_body(b)
    try:
        from l3.config.settings_center import get_center
        from l4.ci_review import CI_SETTING_SUFFIXES, get_service

        center = get_center()
        svc = get_service()
        settings: dict[str, Any] = {}
        effective: dict[str, Any] = {}
        for suffix in sorted(CI_SETTING_SUFFIXES):
            global_key = f"ci.review.{suffix}"
            global_value = center.get(global_key)
            settings[global_key] = global_value
            effective[suffix] = svc._effective(suffix, agent_id, cell_id, global_value)
        return {
            "success": True,
            "settings": settings,
            "effective": effective,
            "scope": {"cell": cell_id, "agent": agent_id},
            "control": {
                "api": {"writable": svc._surface_writable("api")},
                "shell": {"writable": svc._surface_writable("shell")},
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _collect_updates(body: dict) -> dict[str, Any]:
    """Collect key/value updates, dropping control metadata fields."""
    updates: dict[str, Any] = {}
    if "key" in body:
        updates[str(body["key"])] = body.get("value")
        return updates
    for key, value in body.items():
        if key in ("key", "value", "admin", "scope", "cell_id", "agent_id"):
            continue
        updates[key] = value
    return updates


def handle_ci_config_set(body: dict | None = None) -> dict:
    """PUT /api/v2/ci/config — update review switches (whitelisted keys only).

    Accepts direct key/value pairs, an explicit ``{"key","value"}`` form,
    and optional ``scope`` (``{"cell": ...}`` / ``{"agent": ...}``) to write
    a scoped override instead of the global key.  Control-plane keys
    (``ci.control.*``) require ``admin: true`` and skip the surface write
    gate so permissions always remain recoverable.
    """
    b = body or {}
    admin = bool(b.get("admin", False))
    cell_id, agent_id = _scope_from_body(b)
    try:
        from l3.config.settings_center import get_center
        from l4.ci_review import _is_allowed_key, _normalize_key, get_service

        center = get_center()
        svc = get_service()
        updates = _collect_updates(b)

        # Resolve keys: short aliases -> full keys, then inject scope.
        resolved: dict[str, Any] = {}
        for key, value in updates.items():
            full = _normalize_key(key)
            if full.startswith(("ci.review.cell.", "ci.review.agent.")):
                resolved[full] = value
                continue
            if full.startswith("ci.control."):
                resolved[full] = value
                continue
            suffix = full[len("ci.review."):] if full.startswith("ci.review.") else full
            if cell_id:
                resolved[f"ci.review.cell.{cell_id}.{suffix}"] = value
            elif agent_id:
                resolved[f"ci.review.agent.{agent_id}.{suffix}"] = value
            else:
                resolved[f"ci.review.{suffix}"] = value
        rejected = [k for k in resolved if not _is_allowed_key(k)]
        if rejected:
            return {"success": False, "error": f"keys not writable: {rejected}"}
        if not resolved:
            return {"success": False, "error": "no writable keys provided"}

        # Permission model: control-plane keys need admin + skip the surface
        # gate (recoverability); business keys obey the surface gate.
        for key in resolved:
            if key.startswith("ci.control."):
                if not admin:
                    return {"success": False,
                            "error": f"admin confirmation required for {key}"}
            elif not svc._surface_writable("api"):
                return {"success": False,
                        "error": "writes disabled (ci.control.api.writable=false)"}
        for key, value in resolved.items():
            center.set(key, value)
        return {"success": True, "updated": resolved}
    except Exception as e:
        return {"success": False, "error": str(e)}
