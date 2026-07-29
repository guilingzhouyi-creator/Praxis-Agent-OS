"""NetClient — lightweight HTTP client for card pool download, registry queries, etc.

Uses only stdlib (urllib) — no external dependencies.
Supports GET/POST JSON, SSL, and configurable timeouts.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from l1.kernel.params.api import NETWORK_DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

_USER_AGENT = "Praxis-NetClient/1.0"


class NetClient:
    """Generic HTTP client for Praxis internal network requests."""

    @staticmethod
    def get(url: str, timeout: float = NETWORK_DEFAULT_TIMEOUT,
            headers: dict | None = None) -> dict:
        """GET JSON from URL. Returns {"success": True, "data": ...} or error."""
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "application/json",
                    **(headers or {}),
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body) if body.strip() else {}
                return {"success": True, "data": data, "status": resp.status}
        except urllib.error.HTTPError as e:
            return {"success": False, "error": f"HTTP {e.code}: {e.reason}", "status": e.code}
        except urllib.error.URLError as e:
            return {"success": False, "error": f"connection failed: {e.reason}"}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"invalid JSON: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def post(url: str, data: dict, timeout: float = NETWORK_DEFAULT_TIMEOUT,
             headers: dict | None = None) -> dict:
        """POST JSON to URL, return JSON response."""
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **(headers or {}),
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                rbody = resp.read().decode("utf-8", errors="replace")
                rdata = json.loads(rbody) if rbody.strip() else {}
                return {"success": True, "data": rdata, "status": resp.status}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def download(url: str, timeout: float = NETWORK_DEFAULT_TIMEOUT) -> dict:
        """Download raw content from URL (for .card.yaml files)."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                return {"success": True, "content": content, "status": resp.status,
                        "url": url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}
