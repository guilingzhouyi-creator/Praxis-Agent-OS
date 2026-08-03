"""Network service — HTTP client, DNS, proxy, service discovery.

OS-level network configuration and management.
Integrates with kernel settings for configurable defaults.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from l1.kernel.params.api import (
    HTTP_USER_AGENT,
    NETWORK_DEFAULT_TIMEOUT,
    NETWORK_FETCH_MAX_CHARS,
    NETWORK_FETCH_TIMEOUT,
)
from l1.kernel.params.system import NETWORK_RECV_BUF_SIZE
from l3._base import BaseService

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = HTTP_USER_AGENT


@dataclass
class ServiceEndpoint:
    name: str
    host: str
    port: int
    protocol: str = "http"
    health: str = "unknown"
    last_seen: float = 0.0


class NetworkService(BaseService):
    """OS-level network service with config and service discovery."""

    def __init__(self):
        super().__init__("network")
        self._user_agent = _DEFAULT_USER_AGENT
        self._timeout = NETWORK_DEFAULT_TIMEOUT
        self._proxy: dict[str, str] = {}
        self._services: dict[str, ServiceEndpoint] = {}
        self._lock = threading.RLock()
        self._total_requests = 0
        self._failed_requests = 0

    def _on_start(self) -> dict:
        # Load settings from kernel config
        try:
            from l1.kernel.settings import get_settings
            s = get_settings()
            self._timeout = s.get("network.timeout", NETWORK_DEFAULT_TIMEOUT)
            self._user_agent = s.get("network.user_agent", _DEFAULT_USER_AGENT)
        except Exception as e:
            logger.warning("services/network: %s", e)
        return {"success": True, "timeout": self._timeout}

    def _on_stop(self) -> dict:
        with self._lock:
            self._services.clear()
        return {"success": True}

    # ── Configuration ──

    def configure(self, timeout: int | None = None,
                  user_agent: str | None = None,
                  proxy: dict[str, str] | None = None) -> dict:
        """Update network configuration."""
        if timeout is not None:
            self._timeout = timeout
        if user_agent is not None:
            self._user_agent = user_agent
        if proxy is not None:
            with self._lock:
                self._proxy.update(proxy)
        return {"success": True, "timeout": self._timeout, "user_agent": self._user_agent}

    def get_config(self) -> dict:
        with self._lock:
            return {
                "timeout": self._timeout,
                "user_agent": self._user_agent,
                "proxy": dict(self._proxy),
                "total_requests": self._total_requests,
                "failed_requests": self._failed_requests,
            }

    # ── HTTP Client ──

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> dict:
        return self._request("GET", url, headers=headers, timeout=timeout)

    def post(self, url: str, data: Any = None, headers: dict | None = None,
             timeout: int | None = None) -> dict:
        return self._request("POST", url, data=data, headers=headers, timeout=timeout)

    def _request(self, method: str, url: str, data: Any = None,
                 headers: dict | None = None, timeout: int | None = None) -> dict:
        if not url:
            return {"success": False, "error": "url is required"}
        try:
            req_headers = {"User-Agent": self._user_agent}
            if headers:
                req_headers.update(headers)
            body = None
            if data is not None:
                if isinstance(data, (dict, list)):
                    body = json.dumps(data).encode()
                    req_headers.setdefault("Content-Type", "application/json")
                elif isinstance(data, str):
                    body = data.encode()
                elif isinstance(data, bytes):
                    body = data
            req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
            to = timeout or self._timeout
            with urllib.request.urlopen(req, timeout=to) as resp:
                content = resp.read().decode("utf-8", errors="replace")[:NETWORK_RECV_BUF_SIZE]
                with self._lock:
                    self._total_requests += 1
                return {
                    "success": True, "status": resp.status,
                    "headers": dict(resp.headers), "body": content, "url": url,
                }
        except urllib.error.HTTPError as e:
            with self._lock:
                self._total_requests += 1
                self._failed_requests += 1
            return {"success": False, "error": f"HTTP {e.code}: {e.reason}", "status": e.code}
        except urllib.error.URLError as e:
            with self._lock:
                self._failed_requests += 1
            return {"success": False, "error": f"URL error: {e.reason}"}
        except Exception as e:
            with self._lock:
                self._failed_requests += 1
            return {"success": False, "error": str(e)}

    def fetch_text(self, url: str, max_chars: int = NETWORK_FETCH_MAX_CHARS) -> dict:
        r = self.get(url)
        if r["success"]:
            r["body"] = r["body"][:max_chars]
        return r

    def download(self, url: str, path: str) -> dict:
        try:
            urllib.request.urlretrieve(url, path)
            size = os.path.getsize(path)
            return {"success": True, "path": path, "size": size, "url": url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── DNS ──

    def resolve(self, host: str) -> dict:
        """DNS lookup."""
        try:
            addrs = socket.getaddrinfo(host, 80)
            ips = list(set(a[4][0] for a in addrs))
            return {"success": True, "host": host, "ips": ips, "count": len(ips)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Service Discovery ──

    def register_service(self, name: str, host: str, port: int,
                         protocol: str = "http") -> dict:
        with self._lock:
            self._services[name] = ServiceEndpoint(
                name=name, host=host, port=port, protocol=protocol, last_seen=time.time())
        return {"success": True, "name": name, "url": f"{protocol}://{host}:{port}"}

    def find_service(self, name: str) -> dict:
        with self._lock:
            svc = self._services.get(name)
            if not svc:
                return {"success": False, "error": f"service not found: {name}"}
            return {"success": True, "name": name, "url": f"{svc.protocol}://{svc.host}:{svc.port}",
                    "host": svc.host, "port": svc.port, "healthy": svc.health}

    def list_services(self) -> dict:
        with self._lock:
            return {"success": True, "services": [
                {"name": n, "url": f"{s.protocol}://{s.host}:{s.port}", "health": s.health}
                for n, s in self._services.items()
            ], "count": len(self._services)}

    def health_check(self, name: str) -> dict:
        """Check if a registered service is reachable."""
        r = self.find_service(name)
        if not r["success"]:
            return r
        url = r["url"]
        result = self.get(url, timeout=NETWORK_FETCH_TIMEOUT)
        with self._lock:
            svc = self._services.get(name)
            if svc:
                svc.health = "healthy" if result.get("success") else "unreachable"
                svc.last_seen = time.time()
        return {"success": True, "name": name, "health": svc.health if svc else "unknown"}

    # ── Stats ──

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "failed_requests": self._failed_requests,
                "services": len(self._services),
                "timeout": self._timeout,
                "user_agent": self._user_agent,
            }


_service: NetworkService | None = None
_service_lock = threading.Lock()


def get_service() -> NetworkService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = NetworkService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None
