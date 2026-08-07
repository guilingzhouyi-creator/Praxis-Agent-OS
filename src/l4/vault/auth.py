"""Auth service 鈥?key management, signing, encryption, hash, token lifecycle.

Security layer for Agent OS:
- HMAC signing/verification
- Fernet encryption/decryption
- Key vault management
- Hash computation
- Auth token lifecycle (issue/verify/revoke/refresh) 鈥?backs the AuthPort
  used by L3 security gates and the /api/v2/auth/* contract.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
import uuid

from l1.kernel.params.api import AUTH_TOKEN_TTL_SECONDS
from l1.kernel.params.system import AUTH_SIGN_KEY_BYTES, HASH_TRUNC_LONG
from l1.kernel.ports import AuthPort
from l3._base import BaseService

logger = logging.getLogger(__name__)


class KeyVault:
    """Thread-safe key-value store for secrets."""

    def __init__(self):
        self._keys: dict[str, str] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: str) -> None:
        """Store a secret value under the given key."""
        with self._lock:
            self._keys[key] = value

    def get(self, key: str, default: str = "") -> str:
        """Return the stored value for the key, or the default when absent."""
        with self._lock:
            return self._keys.get(key, default)

    def delete(self, key: str) -> bool:
        """Delete the key; return True when it existed."""
        with self._lock:
            return self._keys.pop(key, None) is not None

    def list(self) -> list[str]:
        """Return all stored key names."""
        with self._lock:
            return list(self._keys.keys())


class AuthService(AuthPort, BaseService):
    """Authentication and cryptography service (implements the AuthPort adapter)."""

    def __init__(self):
        super().__init__("auth")
        self._vault = KeyVault()
        self._sign_key = os.urandom(AUTH_SIGN_KEY_BYTES)
        self._revoked: dict[str, float] = {}  # token_id -> token expiry (lazy-pruned)
        self._token_lock = threading.Lock()

    def _on_start(self) -> dict:
        # Initialize default keys
        self._vault.set("service_key", self._sign_key.hex())
        return {"success": True}

    def _on_stop(self) -> dict:
        self._vault = KeyVault()
        return {"success": True}

    def sign(self, data: str, key: str | None = None) -> dict:
        """HMAC-SHA256 sign the data, optionally with an explicit key."""
        k = bytes.fromhex(key) if key else self._sign_key
        sig = hmac.new(k, data.encode(), hashlib.sha256).hexdigest()
        return {"success": True, "signature": sig, "algorithm": "HMAC-SHA256"}

    def verify(self, data: str, signature: str, key: str | None = None) -> dict:
        """Verify the HMAC signature over the data."""
        k = bytes.fromhex(key) if key else self._sign_key
        expected = hmac.new(k, data.encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(expected, signature)
        return {"success": True, "valid": valid}

    def hash(self, data: str, algorithm: str = "sha256") -> dict:
        """Hash the data with the given algorithm and return the digest."""
        try:
            h = hashlib.new(algorithm, data.encode())
            return {"success": True, "hash": h.hexdigest(), "algorithm": algorithm, "size": h.digest_size}
        except ValueError:
            return {"success": False, "error": f"unsupported algorithm: {algorithm}"}

    def encrypt(self, data: str) -> dict:
        """One-shot Fernet encryption.

        WARNING: a fresh Fernet key is generated on every call and
        returned to the caller as ``key``. The caller MUST persist this
        key (out of band) or the ciphertext cannot be decrypted. This is
        intentional for ephemeral/sealed-payload use cases; for at-rest
        encryption use ``CredentialVault`` (AES-GCM with persisted salt)
        instead. Do NOT log or transmit the returned ``key`` alongside
        the ciphertext.
        """
        try:
            from cryptography.fernet import Fernet

            key = Fernet.generate_key()
            f = Fernet(key)
            encrypted = f.encrypt(data.encode())
            return {"success": True, "encrypted": encrypted.decode(), "key": key.decode(), "algorithm": "Fernet"}
        except ImportError:
            return {"success": False, "error": "cryptography not installed"}

    def decrypt(self, encrypted: str, key: str) -> dict:
        """Decrypt a Fernet ciphertext with the caller-supplied ``key``.

        ``key`` is the one-shot Fernet key returned by ``encrypt``; the
        caller is responsible for storing it securely between calls.
        """
        try:
            from cryptography.fernet import Fernet

            f = Fernet(key.encode())
            decrypted = f.decrypt(encrypted.encode())
            return {"success": True, "decrypted": decrypted.decode(), "algorithm": "Fernet"}
        except ImportError:
            return {"success": False, "error": "cryptography not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def vault_set(self, key: str, value: str) -> dict:
        """Store a secret in the vault under the given key."""
        self._vault.set(key, value)
        return {"success": True}

    def vault_get(self, key: str) -> dict:
        """Fetch a secret from the vault by key."""
        value = self._vault.get(key)
        return {"success": True, "key": key, "found": bool(value), "length": len(value) if value else 0}

    def vault_list(self) -> dict:
        """List all vault keys with their count."""
        keys = self._vault.list()
        return {"success": True, "keys": keys, "count": len(keys)}

    # 鈹€鈹€ Token lifecycle (AuthPort adapter surface) 鈹€鈹€

    def issue_token(self, identity: str, ttl: float = AUTH_TOKEN_TTL_SECONDS) -> dict:
        """Issue a signed auth token for an identity.

        Token payload: ``identity|expires_at`` HMAC-SHA256 signed with the
        service key. Returns ``{success, token, expires_at, identity}``.
        """
        if not (identity or "").strip():
            return {"success": False, "error": "identity required"}
        lifetime = ttl if ttl > 0 else AUTH_TOKEN_TTL_SECONDS
        expires_at = time.time() + lifetime
        token_id = uuid.uuid4().hex[:HASH_TRUNC_LONG]
        payload = f"{identity}|{int(expires_at)}|{token_id}"
        sig = hmac.new(self._sign_key, payload.encode(), hashlib.sha256).hexdigest()
        token = f"{payload}|{sig}"
        return {"success": True, "token": token, "expires_at": expires_at, "identity": identity, "ttl": lifetime}

    def verify_token(self, token: str) -> dict:
        """Verify a token. Returns ``{valid, identity, error}``."""
        if not token:
            return {"valid": False, "identity": "", "error": "missing token"}
        try:
            identity, expires_raw, token_id, sig = token.split("|", 3)
        except ValueError:
            return {"valid": False, "identity": "", "error": "malformed token"}
        payload = f"{identity}|{expires_raw}|{token_id}"
        expected = hmac.new(self._sign_key, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return {"valid": False, "identity": "", "error": "signature mismatch"}
        self._prune_revoked()
        with self._token_lock:
            if token_id in self._revoked:
                return {"valid": False, "identity": "", "error": "token revoked"}
        if float(expires_raw) < time.time():
            return {"valid": False, "identity": "", "error": "token expired"}
        return {"valid": True, "identity": identity, "error": ""}

    def revoke_token(self, token: str) -> dict:
        """Revoke a token, invalidating it immediately."""
        if not token:
            return {"success": False, "error": "missing token"}
        try:
            _, expires_raw, token_id, _ = token.split("|", 3)
            expires_at = float(expires_raw)
        except (ValueError, TypeError):
            return {"success": False, "error": "malformed token"}
        with self._token_lock:
            self._revoked[token_id] = expires_at
        return {"success": True, "revoked": token_id}

    def _prune_revoked(self, now: float | None = None) -> int:
        """Drop revoked-token records whose token has naturally expired (bounded growth)."""
        now = now or time.time()
        pruned = 0
        with self._token_lock:
            expired = [tid for tid, exp in self._revoked.items() if exp <= now]
            for tid in expired:
                del self._revoked[tid]
                pruned += 1
        return pruned

    def refresh_token(self, token: str) -> dict:
        """Exchange a valid token for a new one with a fresh expiry."""
        v = self.verify_token(token)
        if not v.get("valid"):
            return {"success": False, "error": v.get("error", "invalid token")}
        return self.issue_token(v["identity"])


_service: AuthService | None = None
_service_lock = threading.Lock()


def get_service() -> AuthService:
    """Return the process-wide AuthService singleton, self-registering the auth port."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = AuthService()
                _service.start()
                # Self-register on the auth port so L3 security gates can
                # resolve the adapter without boot-time wiring (K domain).
                try:
                    from l1.kernel.ports import register_port

                    register_port("auth", _service)
                except Exception:
                    logger.debug("auth: port self-registration skipped")
    return _service


def reset_service() -> None:
    """Stop and clear the AuthService singleton."""
    global _service
    if _service:
        _service.stop()
    _service = None
