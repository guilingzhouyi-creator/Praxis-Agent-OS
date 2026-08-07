"""User profile API handlers — profile surface over the side-channel service.

Endpoints:
  GET    /api/v2/profile                     — user list + overview
  GET    /api/v2/profile/{user_id}           — profile snapshot (kinds filter)
  POST   /api/v2/profile/{user_id}/ingest    — record a typed fact
  POST   /api/v2/profile/{user_id}/refine    — synthesize trait entries
  GET    /api/v2/profile/{user_id}/export    — portable JSON payload
  POST   /api/v2/profile/{user_id}/import    — restore a previously exported profile
  DELETE /api/v2/profile/{user_id}           — clear a user's profile
"""

from __future__ import annotations


def _get_profile():
    from l3.services.user_profile import get_service

    return get_service()


def _require_user(user_id: str) -> dict | None:
    """Return an error dict when user_id is missing."""
    if not (user_id or "").strip():
        return {"success": False, "error": "user_id required"}
    return None


def handle_profile_list(body: dict | None = None) -> dict:
    """GET /api/v2/profile — list users with live profiles."""
    try:
        svc = _get_profile()
        return {"success": True, "users": svc._store.all_users(), "count": svc._store.count()}
    except Exception as e:
        return {"success": False, "error": f"profile list failed: {e}"}


def handle_profile_get(body: dict | None = None, user_id: str = "") -> dict:
    """GET /api/v2/profile/{user_id} — profile snapshot (optional ?kinds=)."""
    err = _require_user(user_id)
    if err:
        return err
    b = body or {}
    kinds = None
    raw_kinds = str(b.get("kinds") or "")
    if raw_kinds:
        kinds = tuple(k.strip() for k in raw_kinds.split(",") if k.strip())
    try:
        snap = _get_profile().get_profile(user_id, kinds=kinds)
    except Exception as e:
        return {"success": False, "error": f"profile get failed: {e}"}
    return {"success": True, "profile": snap}


def handle_profile_ingest(body: dict | None = None, user_id: str = "") -> dict:
    """POST /api/v2/profile/{user_id}/ingest — record a typed fact."""
    err = _require_user(user_id)
    if err:
        return err
    b = body or {}
    kind = str(b.get("kind") or "").strip()
    if not kind:
        return {"success": False, "error": "kind required"}
    if "value" not in b:
        return {"success": False, "error": "value required"}
    try:
        confidence = float(b.get("confidence") or 0.6)
        ttl = float(b.get("ttl") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "confidence/ttl must be numbers"}
    return _get_profile().ingest(
        user_id=user_id,
        kind=kind,
        value=b["value"],
        source=str(b.get("source") or "api"),
        confidence=confidence,
        context=b.get("context") if isinstance(b.get("context"), dict) else None,
        ttl=ttl,
    )


def handle_profile_refine(body: dict | None = None, user_id: str = "") -> dict:
    """POST /api/v2/profile/{user_id}/refine — synthesize trait entries."""
    err = _require_user(user_id)
    if err:
        return err
    try:
        r = _get_profile().refine(user_id)
    except Exception as e:
        return {"success": False, "error": f"refine failed: {e}"}
    return r


def handle_profile_export(body: dict | None = None, user_id: str = "") -> dict:
    """GET /api/v2/profile/{user_id}/export — portable JSON payload."""
    err = _require_user(user_id)
    if err:
        return err
    try:
        payload = _get_profile().export(user_id)
    except Exception as e:
        return {"success": False, "error": f"export failed: {e}"}
    return {"success": True, "payload": payload}


def handle_profile_import(body: dict | None = None, user_id: str = "") -> dict:
    """POST /api/v2/profile/{user_id}/import — restore a profile payload."""
    err = _require_user(user_id)
    if err:
        return err
    b = body or {}
    payload = b.get("payload")
    if not isinstance(payload, dict):
        return {"success": False, "error": "payload required"}
    replace = bool(b.get("replace"))
    try:
        r = _get_profile().import_profile(user_id, payload, replace=replace)
    except Exception as e:
        return {"success": False, "error": f"import failed: {e}"}
    return r


def handle_profile_clear(body: dict | None = None, user_id: str = "") -> dict:
    """DELETE /api/v2/profile/{user_id} — clear a user's profile."""
    err = _require_user(user_id)
    if err:
        return err
    try:
        r = _get_profile().clear(user_id)
    except Exception as e:
        return {"success": False, "error": f"clear failed: {e}"}
    return r
