"""Auth API handlers — token login/logout/refresh contract.

Endpoints:
  POST /api/v2/auth/login    — issue a token for an identity
  POST /api/v2/auth/logout   — revoke a token
  POST /api/v2/auth/refresh  — exchange a valid token for a new one
"""

from __future__ import annotations


def _get_auth():
    from l4.vault.auth import get_service

    return get_service()


def handle_auth_login(body: dict | None = None) -> dict:
    """POST /api/v2/auth/login — issue a signed token for an identity."""
    b = body or {}
    identity = str(b.get("identity") or "").strip()
    if not identity:
        return {"success": False, "error": "identity required"}
    ttl = 0.0
    try:
        ttl = float(b.get("ttl") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "ttl must be a number"}
    try:
        r = _get_auth().issue_token(identity, ttl=ttl)
    except Exception as e:
        return {"success": False, "error": f"login failed: {e}"}
    return {"success": True, "token": r.get("token"), "identity": identity, "expires_at": r.get("expires_at")}


def handle_auth_logout(body: dict | None = None) -> dict:
    """POST /api/v2/auth/logout — revoke a token immediately."""
    b = body or {}
    token = str(b.get("token") or "").strip()
    if not token:
        return {"success": False, "error": "token required"}
    try:
        r = _get_auth().revoke_token(token)
    except Exception as e:
        return {"success": False, "error": f"logout failed: {e}"}
    return {"success": True, "revoked": r.get("revoked")}


def handle_auth_refresh(body: dict | None = None) -> dict:
    """POST /api/v2/auth/refresh — exchange a valid token for a new one."""
    b = body or {}
    token = str(b.get("token") or "").strip()
    if not token:
        return {"success": False, "error": "token required"}
    try:
        r = _get_auth().refresh_token(token)
    except Exception as e:
        return {"success": False, "error": f"refresh failed: {e}"}
    if not r.get("success"):
        return {"success": False, "error": r.get("error", "invalid token")}
    return {"success": True, "token": r.get("token"), "identity": r.get("identity"), "expires_at": r.get("expires_at")}


# Re-export for introspection tools that scan module-level handler names.
__all__: list[str] = [n for n in globals() if n.startswith("handle_auth")]
