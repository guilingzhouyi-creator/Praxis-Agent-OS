"""CredentialVault — LLM API credential vault.

API keys are encrypted on disk using AES-GCM, decrypted into memory at boot.
Supports multiple providers (openai/anthropic/ollama/...),
env var fallback, runtime updates, export (without plaintext keys).

Architecture:
  credential_vault.json (AES-GCM encrypted)
       ↓ decrypted at boot
  CredentialVault (in-memory dict, read-write)
       Read by provider on call
  llm_providers.py / AgentLoop
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

from l1.kernel.params.system import VAULT_FILENAME, VAULT_KEY_BYTES, VAULT_NONCE_LENGTH, VAULT_SALT_FILENAME
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)

_VAULT_PATH: str = ""
_VAULT_KEY: bytes = b""
_vault: dict[str, dict[str, str]] = {}  # provider → {key_name: value}
_lock = threading.Lock()


def init_vault(vault_dir: str = "") -> dict:
    """Initialize the credential vault. Creates encrypted store if missing.

    Uses a derived key from PRAXIS_DATA_DIR + machine fingerprint.
    """
    global _VAULT_PATH, _VAULT_KEY
    with _lock:
        data_dir = vault_dir or os.environ.get("PRAXIS_DATA_DIR", _gp().data_dir)
        os.makedirs(data_dir, exist_ok=True)
        _VAULT_PATH = os.path.join(data_dir, VAULT_FILENAME)

        # Derive encryption key from machine-local secret
        _VAULT_KEY = _derive_key(data_dir)

        # Load existing vault or create empty
        _load_vault()
        logger.info("credential vault initialized: %s (%d providers)",
                    _VAULT_PATH, len(_vault))
    return {"success": True, "path": _VAULT_PATH, "providers": len(_vault)}


def get_credential(provider: str, key_name: str = "api_key",
                   env_fallback: str = "") -> str:
    """Get a credential value. Checks vault first, then env var.

    Args:
        provider: Provider name (e.g. "openai", "anthropic", "ollama")
        key_name: Key within provider (e.g. "api_key", "api_url")
        env_fallback: Env var name to check if not in vault.

    Returns:
        Credential value string, or "" if not found.
    """
    with _lock:
        prov = _vault.get(provider, {})
        val = prov.get(key_name, "")
        if val:
            return val
    if env_fallback:
        return os.environ.get(env_fallback, "")
    return ""


def set_credential(provider: str, key_name: str, value: str) -> dict:
    """Set a credential value and persist to encrypted store."""
    with _lock:
        _vault.setdefault(provider, {})[key_name] = value
        ok = _save_vault()
    if ok:
        logger.info("credential set: %s/%s (len=%d)", provider, key_name, len(value))
    return {"success": ok, "provider": provider, "key": key_name}


def delete_credential(provider: str, key_name: str = "") -> dict:
    """Delete credential(s). If key_name is empty, deletes entire provider."""
    with _lock:
        if key_name:
            prov = _vault.get(provider)
            if prov:
                prov.pop(key_name, None)
        else:
            _vault.pop(provider, None)
        ok = _save_vault()
    return {"success": ok, "provider": provider, "key": key_name or "*"}


def get_credential_for_provider(provider: str) -> dict[str, str]:
    """Get ALL credentials for a provider with env var fallback.

    Checks vault first, then env vars from _PROVIDER_ENV_MAP.
    Returns dict of {key_name: value} for all known keys.
    Unset keys are omitted.
    """
    result: dict[str, str] = {}
    with _lock:
        prov = _vault.get(provider, {})
        result.update(prov)
    for env_name in _PROVIDER_ENV_MAP.get(provider, []):
        val = os.environ.get(env_name)
        if val:
            key = env_name.lower().replace("api_", "").replace("_key", "_key")  # normalize
            if env_name.endswith("_KEY"):
                result["api_key"] = val
            elif env_name.endswith("_URL"):
                result["api_url"] = val
            elif env_name.endswith("_MODEL"):
                result["model"] = val
    return result


def list_providers() -> list[dict]:
    """List all providers and their key names (without values)."""
    with _lock:
        return [
            {"provider": p, "keys": list(k.keys()), "count": len(k)}
            for p, k in _vault.items()
        ]


def list_credentials(provider: str) -> dict:
    """List credential key names for a provider (without values)."""
    with _lock:
        prov = _vault.get(provider, {})
        return {
            "provider": provider,
            "keys": list(prov.keys()),
            "count": len(prov),
            "has_env_fallback": any(
                os.environ.get(e) for e in _provider_env_map().get(provider, [])
            ),
        }


def export_vault_status() -> dict:
    """Export vault status for monitoring (no key values)."""
    with _lock:
        return {
            "path": _VAULT_PATH,
            "exists": bool(os.path.exists(_VAULT_PATH)) if _VAULT_PATH else False,
            "providers": len(_vault),
            "provider_list": list(_vault.keys()),
            "total_keys": sum(len(k) for k in _vault.values()),
        }


# ── Internal ──

_PROVIDER_ENV_MAP: dict[str, list[str]] = {
    "openai":    ["OPENAI_API_KEY", "OPENAI_API_URL", "OPENAI_MODEL"],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_API_URL", "ANTHROPIC_MODEL"],
    "deepseek":  ["DEEPSEEK_API_KEY"],
    "ollama":    ["OLLAMA_URL", "OLLAMA_MODEL"],
}


def _provider_env_map() -> dict[str, list[str]]:
    return dict(_PROVIDER_ENV_MAP)


def _derive_key(seed_dir: str) -> bytes:
    """Derive an AES-256 key from a random salt file (created on first boot).

    If no salt file exists, generates 32 bytes from secrets.token_bytes
    and persists it alongside the vault. This ensures the key is unique
    per installation and not derivable from public info alone.
    """
    salt_path = os.path.join(os.path.dirname(seed_dir) or ".", VAULT_SALT_FILENAME)
    try:
        if os.path.exists(salt_path):
            with open(salt_path, "rb") as f:
                salt = f.read()
        else:
            salt = os.urandom(VAULT_KEY_BYTES)
            with open(salt_path, "wb") as f:
                f.write(salt)
        return hashlib.sha256(salt).digest()
    except Exception:
        # Fallback: ephemeral random key (vault unusable after restart)
        return hashlib.sha256(os.urandom(VAULT_KEY_BYTES)).digest()


def _load_vault() -> None:
    global _vault
    if not _VAULT_PATH or not os.path.exists(_VAULT_PATH):
        _vault = {}
        return
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce_len = VAULT_NONCE_LENGTH
        with open(_VAULT_PATH, "rb") as fh:
            data = fh.read()
        nonce = data[:nonce_len]
        ciphertext = data[nonce_len:]
        aesgcm = AESGCM(_VAULT_KEY[:32])
        plain = aesgcm.decrypt(nonce, ciphertext, None)
        _vault = json.loads(plain.decode())
    except Exception as e:
        logger.warning("credential vault load failed (will recreate or use env): %s", e)
        _vault = {}


def _save_vault() -> bool:
    if not _VAULT_PATH:
        return False
    try:
        import os as _os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = _os.urandom(VAULT_NONCE_LENGTH)
        aesgcm = AESGCM(_VAULT_KEY[:32])
        plain = json.dumps(_vault, indent=2, ensure_ascii=False).encode()
        ciphertext = nonce + aesgcm.encrypt(nonce, plain, None)
        tmp = _VAULT_PATH + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(ciphertext)
        os.replace(tmp, _VAULT_PATH)
        return True
    except Exception as e:
        logger.warning("credential vault save failed: %s", e)
        return False
