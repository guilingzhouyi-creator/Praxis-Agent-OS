"""HTTP connection pool for LLM API calls — persistent per-thread connections.

stdlib-only (``http.client``): each thread reuses its own keep-alive connection
per host, eliminating the TCP/TLS handshake on every LLM call.  Connections are
thread-local because ``http.client`` connections are not thread-safe — a shared
pool would interleave concurrent requests on the same socket.

Broken connections (timeouts, resets, protocol errors) are dropped so the next
call opens a fresh one.  Redirects (301/302/307/308) are followed up to a small
bound to preserve urllib's default behavior.
"""

from __future__ import annotations

import http.client
import threading
from urllib.parse import urlparse

__all__ = ["http_post"]

_MAX_REDIRECTS = 3

_connections = threading.local()


def _get_conn(scheme: str, host: str, port: int, timeout: float) -> http.client.HTTPConnection:
    """Return this thread's persistent connection for (scheme, host, port)."""
    pool = getattr(_connections, "pool", None)
    if pool is None:
        pool = {}
        _connections.pool = pool
    key = (scheme, host, port)
    conn = pool.get(key)
    if conn is None:
        conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(host, port, timeout=timeout)
        pool[key] = conn
    return conn


def _drop_conn(scheme: str, host: str, port: int) -> None:
    """Drop this thread's connection for the host — next call reconnects."""
    pool = getattr(_connections, "pool", None)
    if pool:
        pool.pop((scheme, host, port), None)


def http_post(
    url: str, body: bytes, headers: dict, timeout: float, redirects: int = _MAX_REDIRECTS
) -> tuple[int, bytes, dict]:
    """POST *body* to *url* reusing a persistent per-thread connection.

    Returns ``(status, body_bytes, headers_dict)`` with lower-cased response
    header names.  Raises ``OSError``/``TimeoutError``/``http.client.HTTPException``
    on connection-level failures (the pooled connection is dropped first).
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    conn = _get_conn(scheme, host, port, timeout)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
    except (OSError, TimeoutError, http.client.HTTPException):
        _drop_conn(scheme, host, port)
        raise

    if resp.status in (301, 302, 307, 308) and redirects > 0:
        location = resp_headers.get("location", "")
        if location:
            if location.startswith("/"):
                location = f"{scheme}://{host}{location}"
            return http_post(location, body, headers, timeout, redirects - 1)
    return resp.status, data, resp_headers
