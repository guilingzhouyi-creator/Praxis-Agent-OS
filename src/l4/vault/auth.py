"""Auth service — key management, signing, encryption, hash.

Security layer for Agent OS:
- HMAC signing/verification
- Fernet encryption/decryption
- Key vault management
- Hash computation
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import AUTH_SIGN_KEY_BYTES
from l3._base import BaseService

logger = logging.getLogger(__name__)


class KeyVault:
    """Thread-safe key-value store for secrets."""

    def __init__(self):
        self._keys: dict[str, str] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._keys[key] = value

    def get(self, key: str, default: str = "") -> str:
        with self._lock:
            return self._keys.get(key, default)

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._keys.pop(key, None) is not None

    def list(self) -> list[str]:
        with self._lock:
            return list(self._keys.keys())


class AuthService(BaseService):
    """Authentication and cryptography service."""

    def __init__(self):
        super().__init__("auth")
        self._vault = KeyVault()
        self._sign_key = os.urandom(AUTH_SIGN_KEY_BYTES)

    def _on_start(self) -> dict:
        # Initialize default keys
        self._vault.set("service_key", self._sign_key.hex())
        return {"success": True}

    def _on_stop(self) -> dict:
        self._vault = KeyVault()
        return {"success": True}

    def sign(self, data: str, key: str | None = None) -> dict:
        k = bytes.fromhex(key) if key else self._sign_key
        sig = hmac.new(k, data.encode(), hashlib.sha256).hexdigest()
        return {"success": True, "signature": sig, "algorithm": "HMAC-SHA256"}

    def verify(self, data: str, signature: str, key: str | None = None) -> dict:
        k = bytes.fromhex(key) if key else self._sign_key
        expected = hmac.new(k, data.encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(expected, signature)
        return {"success": True, "valid": valid}

    def hash(self, data: str, algorithm: str = "sha256") -> dict:
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
        self._vault.set(key, value)
        return {"success": True}

    def vault_get(self, key: str) -> dict:
        value = self._vault.get(key)
        return {"success": True, "key": key, "found": bool(value), "length": len(value) if value else 0}

    def vault_list(self) -> dict:
        keys = self._vault.list()
        return {"success": True, "keys": keys, "count": len(keys)}


_service: AuthService | None = None


def get_service() -> AuthService:
    global _service
    if _service is None:
        _service = AuthService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None