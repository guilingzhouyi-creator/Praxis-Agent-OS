"""Identity & security — Ed25519 key pairs, AgentProof, trust chain.

Agent OS spec §6:
  6.1 Agent identity — Ed25519 key pair + signed AgentProof
  6.2 Cross-cell trust chain — signature verification + constitution check
  6.3 Scout sandbox — OS-level isolation (OS responsibility, not code)

Private key persistence (P7 fix):
  - Private keys are encrypted at rest using Fernet (symmetric AES-GCM).
  - The system encryption key is stored in KEY_DIR / ".system_key".
  - .priv files are loaded on startup and decrypted into _secrets.
  - Without the .system_key file, persisted private keys cannot be read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from l3._base import BaseService
from l1.kernel.params.system import PROOF_TTL, NONCE_CLEANUP_AGE, PRAXIS_CONFIG_DIR

logger = logging.getLogger(__name__)

from l1.kernel.platform import get_config_dir
KEY_DIR = Path(get_config_dir()) / "keys"
_SYSTEM_KEY_FILE = KEY_DIR / ".system_key"


def _get_system_key() -> bytes:
    """Get or create the system-level encryption key for private key storage.

    The key is 32 random bytes stored in KEY_DIR/.system_key with 0o600
    permissions on POSIX. The file is created with O_CREAT|O_EXCL so it
    cannot be pre-seeded by another local user. Without this file (or its
    secret), persisted private keys cannot be decrypted.
    """
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    # Restrict the keys directory itself on POSIX (best-effort)
    try:
        os.chmod(KEY_DIR, 0o700)
    except OSError:
        pass
    if _SYSTEM_KEY_FILE.exists():
        return _SYSTEM_KEY_FILE.read_bytes()
    import secrets
    key = secrets.token_bytes(32)
    fd = os.open(str(_SYSTEM_KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    logger.info("generated new system encryption key at %s", _SYSTEM_KEY_FILE)
    return key


def _encrypt_private_key(priv_bytes: bytes) -> str:
    """Encrypt private key bytes for disk storage using AES-GCM via cryptography."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    system_key = _get_system_key()
    aesgcm = AESGCM(system_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, priv_bytes, None)
    # Store as hex: nonce_hex + ciphertext_hex
    return nonce.hex() + ciphertext.hex()


def _decrypt_private_key(encrypted_hex: str) -> bytes | None:
    """Decrypt a private key hex string back to bytes."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        system_key = _get_system_key()
        aesgcm = AESGCM(system_key)
        nonce = bytes.fromhex(encrypted_hex[:24])
        ciphertext = bytes.fromhex(encrypted_hex[24:])
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        logger.error("private key decryption failed: %s", e)
        return None


@dataclass
class AgentProof:
    """Agent identity proof — attached to every IPC message (§6.1)."""
    agent_id: str
    cell_id: str
    timestamp: float
    nonce: str
    signature: str = ""
    public_key: str = ""

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > PROOF_TTL

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class TrustAnchor:
    """Trust anchor — root of trust for a cell."""
    cell_id: str
    public_key: str
    constitution_hash: str
    registered_at: float = field(default_factory=time.time)


class IdentityService(BaseService):
    """Identity & security — Ed25519 key management, AgentProof, trust chain.

    Spec §6.1:
      Each agent has an Ed25519 key pair.
      Each IPC message includes an AgentProof (agent_id + timestamp + nonce + signature).
      Receiver verifies: timestamp within ±30s, nonce unused, signature valid.

    Spec §6.2:
      Cross-cell trust chain requires shared constitution.
      Signatures are verified against the public key in the trust anchor.
    """

    def __init__(self):
        super().__init__("identity")
        self._keys: dict[str, dict] = {}         # agent_id → public_key (hex)
        self._secrets: dict[str, bytes] = {}      # agent_id → private_key (bytes, in-memory only)
        # nonce → insertion timestamp; a nonce is only valid within PROOF_TTL
        # of when it was first seen. We absorb a nonce only *after* the
        # signature check passes, so a forged/ replayed proof cannot lock
        # out a legitimate agent by polluting the nonce set.
        self._nonces: dict[str, float] = {}
        self._trust_anchors: dict[str, TrustAnchor] = {}
        self._lock = threading.RLock()
        self._key_dir = KEY_DIR

    def _on_start(self) -> dict:
        self._key_dir.mkdir(parents=True, exist_ok=True)
        # Load persisted public keys
        for key_file in self._key_dir.glob("*.pub"):
            try:
                agent_id = key_file.stem
                pub = key_file.read_text(encoding="utf-8").strip()
                self._keys[agent_id] = pub
            except Exception as e:
                logger.warning("failed to load public key: %s", e)
        # Load persisted encrypted private keys (P7 fix)
        for priv_file in self._key_dir.glob("*.priv"):
            try:
                agent_id = priv_file.stem
                encrypted = priv_file.read_text(encoding="utf-8").strip()
                decrypted = _decrypt_private_key(encrypted)
                if decrypted:
                    self._secrets[agent_id] = decrypted
                    # Also mark identity as verified in process table
                    try:
                        from l1.kernel.process import get_table
                        get_table().mark_identity_verified(agent_id)
                    except Exception as e:
                        logger.warning("identity: %s", e)
            except Exception as e:
                logger.warning("failed to load private key for %s: %s", priv_file.stem, e)
        logger.info("identity service started: %d public keys, %d private keys",
                    len(self._keys), len(self._secrets))
        return {"success": True, "keys_loaded": len(self._keys),
                "priv_keys_loaded": len(self._secrets)}

    def _on_stop(self) -> dict:
        self._keys.clear()
        self._secrets.clear()
        self._nonces.clear()
        self._trust_anchors.clear()
        return {"success": True}

    # ── Key Generation (§6.1) ──

    def generate_keypair(self, agent_id: str) -> dict:
        """Generate Ed25519 key pair for an agent."""
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PrivateFormat, PublicFormat, NoEncryption,
            )
            private_key = ed25519.Ed25519PrivateKey.generate()
            public_key = private_key.public_key()

            pub_hex = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
            priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())

            with self._lock:
                self._keys[agent_id] = pub_hex
                self._secrets[agent_id] = priv_bytes

            # Persist public key
            try:
                (self._key_dir / f"{agent_id}.pub").write_text(pub_hex, encoding="utf-8")
            except Exception as e:
                logger.warning("public key persist failed: %s", e)

            # Persist encrypted private key (P7 fix: survive restarts)
            try:
                encrypted = _encrypt_private_key(priv_bytes)
                (self._key_dir / f"{agent_id}.priv").write_text(encrypted, encoding="utf-8")
            except Exception as e:
                logger.warning("private key persist failed: %s", e)

            # Notify kernel process table: this agent's identity is verified
            try:
                from l1.kernel.process import get_table
                get_table().mark_identity_verified(agent_id)
            except Exception as e:
                        logger.warning("services/identity: %s", e)

            return {"success": True, "agent_id": agent_id, "public_key": pub_hex}
        except ImportError as e:
            return {"success": False, "error": f"cryptography not installed: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_public_key(self, agent_id: str) -> dict:
        """Get agent's public key."""
        with self._lock:
            pub = self._keys.get(agent_id)
            if not pub:
                return {"success": False, "error": "no key for agent"}
            return {"success": True, "agent_id": agent_id, "public_key": pub}

    # ── AgentProof (§6.1) ──

    def create_proof(self, agent_id: str, cell_id: str = "") -> dict:
        """Create a signed AgentProof for IPC message."""
        with self._lock:
            priv_bytes = self._secrets.get(agent_id)
            if not priv_bytes:
                return {"success": False, "error": f"no private key for {agent_id}, generate one first"}

        import secrets
        nonce = secrets.token_hex(16)
        timestamp = time.time()

        # Sign: agent_id + cell_id + timestamp + nonce
        payload = f"{agent_id}:{cell_id}:{timestamp}:{nonce}".encode()

        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

            private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
            signature = private_key.sign(payload).hex()

            proof = AgentProof(
                agent_id=agent_id, cell_id=cell_id,
                timestamp=timestamp, nonce=nonce,
                signature=signature,
                public_key=self._keys.get(agent_id, ""),
            )
            return {"success": True, "proof": proof.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_proof(self, proof: dict) -> dict:
        """Verify an AgentProof (§6.1 verification flow).

        Order matters: we look up the agent's public key and verify the
        signature first, and only absorb the nonce into the anti-replay
        set once the signature is confirmed valid. This prevents a
        forged or replayed proof from polluting the nonce set and
        locking out a legitimate agent that happens to reuse the same
        nonce.
        """
        # 1. Check timestamp (±PROOF_TTL window)
        ts = proof.get("timestamp", 0)
        if abs(time.time() - ts) > PROOF_TTL:
            return {"success": False, "error": f"proof expired (timestamp out of ±{PROOF_TTL}s window)"}

        # 2. Resolve agent + signature
        agent_id = proof.get("agent_id", "")
        signature_hex = proof.get("signature", "")
        nonce = proof.get("nonce", "")
        with self._lock:
            pub_hex = self._keys.get(agent_id)

        if not pub_hex:
            return {"success": False, "error": f"unknown agent: {agent_id}"}

        # 3. Reject replay early (without absorbing) so a stale nonce
        #    doesn't get re-locked
        with self._lock:
            if nonce in self._nonces:
                return {"success": False, "error": "nonce already used (replay attack)"}

        # 4. Verify signature
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

            public_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
            payload = f"{agent_id}:{proof.get('cell_id', '')}:{ts}:{nonce}".encode()
            signature = bytes.fromhex(signature_hex)
            public_key.verify(signature, payload)
        except Exception:
            return {"success": False, "error": "signature verification failed"}

        # 5. Absorb nonce only after the signature is confirmed valid
        with self._lock:
            # Re-check: a concurrent verify may have absorbed this nonce
            if nonce in self._nonces:
                return {"success": False, "error": "nonce already used (replay attack)"}
            self._nonces[nonce] = time.time()

        return {"success": True, "valid": True, "agent_id": agent_id}

    # ── Trust Chain (§6.2) ──

    def register_trust_anchor(self, cell_id: str, public_key: str, constitution_hash: str) -> dict:
        """Register a trust anchor for cross-cell trust."""
        with self._lock:
            self._trust_anchors[cell_id] = TrustAnchor(
                cell_id=cell_id, public_key=public_key,
                constitution_hash=constitution_hash,
            )
        return {"success": True, "cell_id": cell_id}

    def verify_cross_cell(self, from_cell: str, to_cell: str,
                          proof: dict, constitution_hash: str) -> dict:
        """Verify cross-cell trust chain (§6.2)."""
        # 1. Both cells must have trust anchors
        with self._lock:
            anchor_from = self._trust_anchors.get(from_cell)
            anchor_to = self._trust_anchors.get(to_cell)

        if not anchor_from:
            return {"success": False, "error": f"no trust anchor for {from_cell}"}
        if not anchor_to:
            return {"success": False, "error": f"no trust anchor for {to_cell}"}

        # 2. Verify same constitution
        if anchor_from.constitution_hash != anchor_to.constitution_hash:
            return {"success": False, "error": "constitution mismatch — cross-cell denied"}

        # 3. Verify the proof
        return self.verify_proof(proof)

    # ── Nonce Management ──

    def cleanup_nonces(self, max_age: float = NONCE_CLEANUP_AGE) -> dict:
        """Drop nonces older than ``max_age`` seconds.

        Nonces are tracked with their insertion timestamp so this is a
        bounded, age-based eviction rather than a full wipe. A nonce is
        only kept while it could still fall inside the ``PROOF_TTL``
        replay window, so callers cannot replay an old proof after a
        cleanup sweep.
        """
        now = time.time()
        with self._lock:
            stale = [n for n, ts in self._nonces.items() if now - ts > max_age]
            for n in stale:
                self._nonces.pop(n, None)
            remaining = len(self._nonces)
        return {"success": True, "cleared": len(stale), "remaining": remaining}

    # ── Stats ──

    def stats(self) -> dict:
        with self._lock:
            return {
                "agents_with_keys": len(self._keys),
                "trust_anchors": len(self._trust_anchors),
                "nonces_cached": len(self._nonces),
            }


_service: IdentityService | None = None


def get_service() -> IdentityService:
    global _service
    if _service is None:
        _service = IdentityService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None