"""API handler mixin — credential vault endpoints.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def credential_status(body: dict | None = None) -> dict:
    """Vault status or per-provider credential listing."""
    try:
        from ..vault.credential_vault import export_vault_status, list_credentials

        provider = (body or {}).get("provider", "")
        if provider:
            return list_credentials(provider)
        return export_vault_status()
    except Exception as e:
        return {"error": str(e)}


def credential_set(body: dict) -> dict:
    """Store a credential for a provider."""
    try:
        from ..vault.credential_vault import set_credential

        provider = body.get("provider", "")
        key = body.get("key", "api_key")
        value = body.get("value", "")
        if not provider or not value:
            return {"error": "provider and value are required"}
        return set_credential(provider, key, value)
    except Exception as e:
        return {"error": str(e)}


def credential_delete(body: dict) -> dict:
    """Delete a stored credential."""
    try:
        from ..vault.credential_vault import delete_credential

        provider = body.get("provider", "")
        key = body.get("key", "")
        if not provider:
            return {"error": "provider is required"}
        return delete_credential(provider, key)
    except Exception as e:
        return {"error": str(e)}
