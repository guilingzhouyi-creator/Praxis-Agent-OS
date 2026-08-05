"""NetClient — lightweight HTTP client with thread-local connection reuse.

Uses only stdlib (http.client) — no external dependencies. Keeps one
keep-alive connection per thread per host so repeated calls to the same
endpoint skip TLS handshake and TCP setup (~50-150ms saved per call).
Stale connections are detected on error and transparently re-established
once.

Supports GET/POST JSON, SSL, and configurable timeouts.

Canonical home of ``NetClient`` (a generic HTTP utility within L3). Consumers
import it directly: ``from l3.net_client import NetClient``.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
import threading
import urllib.parse

from l1.kernel.params.api import NETWORK_DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

_USER_AGENT = "Praxis-NetClient/1.0"

# ── Thread-local connection pool (one keep-alive conn per thread per host) ──


class _Pool:
    def __init__(self):
        self._conns: dict[tuple[str, int, bool], http.client.HTTPConnection] = {}


_pool_local = threading.local()


def _pool() -> dict:
    p = getattr(_pool_local, "pool", None)
    if p is None:
        p = _Pool()
        _pool_local.pool = p
    return p._conns


def _parse_url(url: str) -> tuple[str, str, int, bool]:
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    secure = scheme == "https"
    port = parsed.port or (443 if secure else 80)
    return parsed.hostname or "localhost", port, secure, parsed.path or "/"


def _get_conn(url: str, timeout: float) -> http.client.HTTPConnection:
    host, port, secure, _ = _parse_url(url)
    key = (host, port, secure)
    conns = _pool()
    conn = conns.get(key)
    if conn is None:
        cls = http.client.HTTPSConnection if secure else http.client.HTTPConnection
        conn = cls(host, port, timeout=timeout)
        conns[key] = conn
    return conn


def _discard(url: str) -> None:
    host, port, secure, _ = _parse_url(url)
    key = (host, port, secure)
    conn = _pool().pop(key, None)
    if conn:
        with contextlib.suppress(Exception):
            conn.close()


def _request(method: str, url: str, timeout: float,
             headers: dict | None, body: bytes | None = None) -> tuple[int, bytes]:
    """Perform one request, re-establishing stale connections once."""
    path = urllib.parse.urlparse(url).path or "/"
    if urllib.parse.urlparse(url).query:
        path += "?" + urllib.parse.urlparse(url).query
    for attempt in range(2):
        conn = _get_conn(url, timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, data
        except (http.client.RemoteDisconnected, ConnectionError, OSError,
                http.client.HTTPException) as e:
            _discard(url)
            if attempt == 0:
                logger.debug("net_client: stale connection to %s, retrying: %s", url, e)
                continue
            raise
    raise ConnectionError(f"request failed after retry: {url}")


def _headers(extra: dict | None = None) -> dict:
    h = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _parse_json(data: bytes, url: str) -> dict:
    try:
        return json.loads(data.decode("utf-8", errors="replace")) if data.strip() else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e


class NetClient:
    """Generic HTTP client for Praxis internal network requests."""

    @staticmethod
    def get(url: str, timeout: float = NETWORK_DEFAULT_TIMEOUT,
            headers: dict | None = None) -> dict:
        """GET JSON from URL. Returns {"success": True, "data": ...} or error."""
        try:
            status, data = _request("GET", url, timeout, _headers(headers))
            return {"success": True, "data": _parse_json(data, url), "status": status}
        except http.client.HTTPException as e:
            return {"success": False, "error": f"HTTP {getattr(e, 'code', '?')}: {e}"}
        except (ConnectionError, OSError) as e:
            return {"success": False, "error": f"connection failed: {e}"}
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def post(url: str, data: dict, timeout: float = NETWORK_DEFAULT_TIMEOUT,
             headers: dict | None = None) -> dict:
        """POST JSON to URL, return JSON response."""
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            status, rdata = _request("POST", url, timeout,
                                     _headers({"Content-Type": "application/json",
                                               **(headers or {})}),
                                     body=body)
            return {"success": True, "data": _parse_json(rdata, url), "status": status}
        except http.client.HTTPException as e:
            return {"success": False, "error": f"HTTP {getattr(e, 'code', '?')}: {e}"}
        except (ConnectionError, OSError) as e:
            return {"success": False, "error": f"connection failed: {e}"}
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def download(url: str, timeout: float = NETWORK_DEFAULT_TIMEOUT) -> dict:
        """Download raw content from URL (for .card.yaml files)."""
        try:
            status, data = _request("GET", url, timeout,
                                    {"User-Agent": _USER_AGENT})
            return {"success": True, "content": data.decode("utf-8", errors="replace"),
                    "status": status, "url": url}
        except (ConnectionError, OSError, http.client.HTTPException) as e:
            return {"success": False, "error": str(e), "url": url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}
