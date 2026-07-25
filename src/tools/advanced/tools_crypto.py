"""Encryption/signing tools - 5 kinds.

sign_data, verify_sig, encrypt_file, decrypt_file, hash_data
"""

import hashlib
import hmac
import os
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

_SIGN_KEY = os.urandom(32)


def _cmd_sign_data(args: dict, agent_id: str) -> dict:
    data = args.get("data", "")
    key = args.get("key", _SIGN_KEY.hex())
    if not data:
        return {"success": False, "error": "data is required"}
    if isinstance(key, str):
        key = bytes.fromhex(key)
    sig = hmac.new(key, data.encode(), hashlib.sha256).hexdigest()
    return {"success": True, "data": {"signature": sig, "algorithm": "HMAC-SHA256", "data_length": len(data)}}


def _cmd_verify_sig(args: dict, agent_id: str) -> dict:
    data = args.get("data", "")
    signature = args.get("signature", "")
    key = args.get("key", _SIGN_KEY.hex())
    if not data or not signature:
        return {"success": False, "error": "data and signature are required"}
    if isinstance(key, str):
        key = bytes.fromhex(key)
    expected = hmac.new(key, data.encode(), hashlib.sha256).hexdigest()
    valid = hmac.compare_digest(expected, signature)
    return {"success": True, "data": {"valid": valid, "algorithm": "HMAC-SHA256"}}


def _cmd_encrypt_file(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        f = Fernet(key)
        with open(path, "rb") as fh:
            encrypted = f.encrypt(fh.read())
        enc_path = path + ".enc"
        with open(enc_path, "wb") as fh:
            fh.write(encrypted)
        return {"success": True, "data": {"output": enc_path, "key": key.decode(), "algorithm": "Fernet (AES-128-CBC)"}}
    except ImportError:
        return {"success": False, "error": "cryptography not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_decrypt_file(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    key = args.get("key", "")
    if not path or not key:
        return {"success": False, "error": "path and key are required"}
    try:
        from cryptography.fernet import Fernet
        f = Fernet(key.encode())
        with open(path, "rb") as fh:
            decrypted = f.decrypt(fh.read())
        dec_path = path.replace(".enc", ".dec") if path.endswith(".enc") else path + ".dec"
        with open(dec_path, "wb") as fh:
            fh.write(decrypted)
        return {"success": True, "data": {"output": dec_path, "algorithm": "Fernet (AES-128-CBC)"}}
    except ImportError:
        return {"success": False, "error": "cryptography not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_hash_data(args: dict, agent_id: str) -> dict:
    data = args.get("data", "")
    algorithm = args.get("algorithm", "sha256")
    if not data:
        return {"success": False, "error": "data is required"}
    h = hashlib.new(algorithm, data.encode())
    return {"success": True, "data": {"hash": h.hexdigest(), "algorithm": algorithm, "length": h.digest_size}}


def register_tools() -> None:
    register(ToolSpec(name="sign_data", description="HMAC-SHA256 sign data", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("data", "string", required=True), ParamSpec("key", "string", default="")],
                      handler=_cmd_sign_data))
    register(ToolSpec(name="verify_sig", description="Verify HMAC-SHA256 signature", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("data", "string", required=True), ParamSpec("signature", "string", required=True),
                                  ParamSpec("key", "string", default="")],
                      handler=_cmd_verify_sig))
    register(ToolSpec(name="encrypt_file", description="Encrypt file (requires cryptography library)", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True)],
                      handler=_cmd_encrypt_file))
    register(ToolSpec(name="decrypt_file", description="Decrypt file (requires cryptography library)", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("key", "string", required=True)],
                      handler=_cmd_decrypt_file))
    register(ToolSpec(name="hash_data", description="Compute data hash (SHA-256/SHA-512/MD5)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("data", "string", required=True), ParamSpec("algorithm", "string", default="sha256")],
                      handler=_cmd_hash_data))