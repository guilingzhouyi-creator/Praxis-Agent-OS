"""API Gateway HTTP handler — request parse, auth, middleware chain, SSE.

Extracted from api_gateway.py (P3-1 split): the ``BaseHTTPRequestHandler``
subclass that parses HTTP requests, checks auth, routes through the
gateway's MiddlewareChain, and serves SSE event streams.  The handler is
module-level so api_gateway.py only wires it into the HTTPServer.
"""

# ruff: noqa: N802 — do_* method names are the http.server protocol contract

from __future__ import annotations

import http.server
import json
import logging
import time
from typing import Any

from l1.kernel.params.api import (
    API_CORS_ALLOW_HEADERS,
    API_CORS_ALLOW_METHODS,
    API_CORS_ORIGIN,
    API_GATEWAY_QUEUE_TIMEOUT,
    API_MAX_BODY_BYTES,
)
from l4.api.api_middleware import Request

logger = logging.getLogger(__name__)


def _auth_ok(headers, auth_token: str) -> bool:
    """Return whether a request is authenticated against the gateway.

    Dual-channel: AuthPort-issued login tokens (``Authorization: Bearer``)
    take precedence; the static shared token stays supported on both Bearer
    and the legacy ``X-API-Token`` header.  With no static token configured
    and no AuthPort reachable, requests pass (backward-compatible open
    default — the central security gate decides).
    """
    import hmac

    header = headers.get("Authorization", "")
    if header.startswith("Bearer "):
        token = header[len("Bearer ") :]
        # Channel 1: login-issued tokens via the auth port
        try:
            from l1.kernel.ports import get_port

            auth = get_port("auth")
            v = auth.verify_token(token)
            if v.get("valid"):
                return True
        except Exception:
            pass
        # Channel 2: static shared token
        if auth_token:
            return len(token) == len(auth_token) and hmac.compare_digest(token, auth_token)
        return True
    # Legacy header: static token only
    if auth_token:
        received = headers.get("X-API-Token", "")
        return len(received) == len(auth_token) and hmac.compare_digest(received, auth_token)
    return True


class ApiGatewayHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler: parse → auth → middleware chain → response."""

    gateway: Any | None = None  # set after class definition (class-body scoping)

    def log_message(self, fmt, *args):
        """Suppress default http.server request logging."""
        pass  # Suppress default http.server logging

    def _auth_ok(self) -> bool:
        """Delegate to the module-level auth check (see ``_auth_ok``)."""
        gw = self.gateway
        return _auth_ok(self.headers, gw.auth_token if gw else "")

    def _check_auth(self) -> bool:
        if not self._auth_ok():
            self._json({"error": "unauthorized"}, 401)
            return False
        return True

    def _json(self, data: Any, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > API_MAX_BODY_BYTES:
            self._json({"error": "request body too large"}, 413)
            return {}
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            self._json({"error": "chunked transfer not supported"}, 411)
            return {}
        return json.loads(self.rfile.read(length))

    def _user_id(self) -> str:
        return self.headers.get("X-User-Id", "")

    def _build_request(self, method: str, path: str, body: dict | None = None) -> Request:
        """Build a Request object from HTTP headers + body."""
        import urllib.parse

        parsed = urllib.parse.urlparse(path)
        query = urllib.parse.parse_qs(parsed.query)
        flat_query = {k: v[0] if len(v) == 1 else v for k, v in query.items()}
        return Request(
            method=method,
            path=parsed.path.rstrip("/"),
            headers=dict(self.headers),
            body=body or {},
            query=flat_query,
            raw_body=self.rfile.read(int(self.headers.get("Content-Length", 0))) if body is None else b"",
            user_id=self._user_id(),
        )

    def _handle_via_middleware(self, method: str) -> None:
        """Route request through MiddlewareChain (GET/POST/DELETE)."""
        import urllib.parse

        if not self._check_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        # SSE special handling: long-lived connection.
        # Must match the v2-prefixed route in api_routes.py
        # ("GET /api/v2/events") — keep in sync if the prefix changes.
        if method == "GET" and path == "/api/v2/events":
            self._do_sse()
            return

        # Read body for POST/PUT/DELETE (must happen once, before build_request)
        body = self._read_body() if method in ("POST", "PUT", "DELETE") else {}
        req = self._build_request(method, self.path, body=body)
        gw = self.gateway
        if gw is None:
            self._json({"error": "gateway not initialized"}, 503)
            return
        handler, params = gw._match_route(method, path)
        req.params = params

        def route_handler(r: Request) -> dict:
            """Dispatch the matched route handler for request *r*."""
            return gw._route_dispatch(handler, r.body, r.query, params, r.user_id)

        t0 = time.time()
        resp = gw._middleware.handle(req, route_handler)
        latency_ms = round((time.time() - t0) * 1000, 2)
        self._json(resp.data, resp.status)
        self._expose_request_stats(method, path, resp, req, latency_ms)

    def _expose_request_stats(self, method: str, path: str, resp: Any, req: Request, latency_ms: float) -> None:
        """Expose request timing to the monitoring center (MonitorBus)
        and the statistics center (StatsCenter) — api.request.* metrics
        and stats.api.request events (consumed by /api/v2/stats/live).
        """
        try:
            from l3.bus.monitor_bus import MonitorEvent
            from l3.bus.monitor_bus import get_bus as _mb2

            _mb2().emit(
                MonitorEvent(
                    type="stats.api.request",
                    source="api_gateway",
                    severity="info",
                    message=f"{method} {path} -> {getattr(resp, 'status', '?')}",
                    data={
                        "method": method,
                        "path": path,
                        "status": getattr(resp, "status", 0),
                        "latency_ms": latency_ms,
                        "user_id": req.user_id,
                    },
                )
            )
        except Exception:
            logger.debug("api_gateway: monitor emit failed")
        try:
            from l3.services.stats_center import MetricPoint
            from l3.services.stats_center import get_center as _sc2

            _ts = time.time()
            _tags = {"endpoint": path, "method": method, "status": str(getattr(resp, "status", 0))}
            # Phase E: tag security-domain requests so api.request.*
            # metrics can be sliced by domain.
            if path.startswith("/api/v2/security"):
                _tags["domain"] = "security"
            _sc2().ingest(
                MetricPoint(
                    name="api.request.latency", value=latency_ms, tags=_tags, timestamp=_ts, metric_type="gauge"
                )
            )
            _sc2().ingest(
                MetricPoint(name="api.request.count", value=1.0, tags=_tags, timestamp=_ts, metric_type="counter")
            )
        except Exception:
            logger.debug("api_gateway: stats emit failed")

    def _do_sse(self) -> None:
        """Handle SSE /api/events streaming connection."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
        self.end_headers()
        try:
            import queue as _queue

            from l4.sse.sse_bridge import subscribe

            client = subscribe()
            q = client["queue"]
            while True:
                try:
                    event = q.get(timeout=API_GATEWAY_QUEUE_TIMEOUT)
                    if event is None:
                        break
                    line = f"data: {json.dumps(event, default=str)}\n\n"
                    self.wfile.write(line.encode())
                    self.wfile.flush()
                except _queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("api_gateway: sse client disconnected (normal)")
        except Exception:
            logger.debug("api_gateway: sse handler failed")
        finally:
            try:
                from l4.sse.sse_bridge import unsubscribe as _unsub

                _unsub(client.get("client_id", ""))
            except Exception:
                logger.debug("api_gateway: sse unsubscribe failed")

    def do_POST(self):
        """Serve a POST request through the middleware chain."""
        self._handle_via_middleware("POST")

    def do_PUT(self):
        """Serve a PUT request through the middleware chain."""
        self._handle_via_middleware("PUT")

    def do_GET(self):
        """Serve a GET request through the middleware chain."""
        self._handle_via_middleware("GET")

    def do_DELETE(self):
        """Serve a DELETE request through the middleware chain."""
        self._handle_via_middleware("DELETE")

    def do_OPTIONS(self):
        """Serve a CORS preflight OPTIONS request."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", API_CORS_ALLOW_METHODS)
        self.send_header("Access-Control-Allow-Headers", API_CORS_ALLOW_HEADERS)
        self.end_headers()
