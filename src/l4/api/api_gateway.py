"""API Gateway — HTTP interface with MiddlewareChain + Route dispatching.

Architecture:
  HTTPServer → _Handler (parse) → MiddlewareChain (process) → ApiHandlers (business)

Usage:
  from l4.api.api_gateway import start_api
  start_api()  # default port from kernel.params
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from l1.kernel.params.api import (
    API_CORS_ALLOW_HEADERS,
    API_CORS_ALLOW_METHODS,
    API_CORS_ORIGIN,
    API_GATEWAY_HOST,
    API_GATEWAY_PORT,
    API_GATEWAY_QUEUE_TIMEOUT,
    API_MAX_BODY_BYTES,
    ENV_API_TOKEN,
)
from l4.api.api_middleware import (
    CORSMiddleware,
    LocaleMiddleware,
    MiddlewareChain,
    Request,
)
from l4.api_handlers import ApiHandlers

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
        token = header[len("Bearer "):]
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


# ── Route definition ─────────────────────────────────────────────────────────

@dataclass
class Route:
    """API route entry — method + path pattern + handler.

    Path patterns:
      Exact: "/api/health"
      Wildcard: "/api/card/" → matches "/api/card/<id>"
    """
    method: str = "GET"
    path: str = ""
    handler: Callable = lambda *a, **kw: {}
    description: str = ""


# ── Handler signature cache ─────────────────────────────────────────────────
# inspect.signature() costs ~10-50us per call; handlers are fixed after
# startup, so cache the parameters mapping per handler (module-level dict —
# stable keys, atomic reads/writes under the GIL).
_SIGNATURE_CACHE: dict[Callable, Any] = {}
_NO_SIGNATURE = object()


def _handler_params(handler: Callable) -> Any:
    """Cached ``inspect.signature(handler).parameters`` — None if uninspectable."""
    params = _SIGNATURE_CACHE.get(handler, _NO_SIGNATURE)
    if params is _NO_SIGNATURE:
        try:
            import inspect
            params = inspect.signature(handler).parameters
        except (TypeError, ValueError):
            params = None
        _SIGNATURE_CACHE[handler] = params
    return params


# ── ApiGateway ───────────────────────────────────────────────────────────────

class ApiGateway(ApiHandlers):
    """HTTP API gateway — MiddlewareChain request processing + Route dispatch.

    Backward compatible: ``register_route()``, ``start()``, ``stop()``,
    ``start_api()``, ``stop_api()`` signatures unchanged.
    """

    def __init__(self, host: str = API_GATEWAY_HOST, port: int = API_GATEWAY_PORT,
                 auth_token: str = ""):
        self.host = host
        self.port = port
        self.auth_token = auth_token or os.environ.get(ENV_API_TOKEN, "")
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._routes: list[Route] = []
        # O(1) exact-match index: (method, path) → (handler, {}) — rebuilt
        # lazily whenever the route table changes (register_route or direct
        # _routes mutation), so it can never go stale.
        self._exact_index: dict[tuple[str, str], tuple[Callable, dict]] = {}
        self._index_route_count = -1

        # Middleware chain — built once at init
        self._middleware = MiddlewareChain([
            CORSMiddleware(
                origin=API_CORS_ORIGIN,
                methods=API_CORS_ALLOW_METHODS,
                headers=API_CORS_ALLOW_HEADERS,
            ),
            LocaleMiddleware(),
        ])

        self._register_defaults()

    # ── Route registration ───────────────────────────────────────────────

    def register_route(self, method: str, path: str,
                       handler: Callable, description: str = "") -> None:
        """Register a new API route."""
        self._routes.append(Route(
            method=method, path=path,
            handler=handler, description=description,
        ))
        self._index_route_count = -1  # exact index needs a lazy rebuild

    def _rebuild_exact_index(self) -> None:
        """Rebuild the (method, path) → handler index from ``_routes``."""
        self._exact_index = {
            (r.method, r.path): (r.handler, {})
            for r in self._routes
            if not r.path.endswith("/") and "{" not in r.path
        }
        self._index_route_count = len(self._routes)

    def _register_defaults(self) -> None:
        """Load all routes from centralized api_routes.py + external modules."""
        import importlib

        from .api_routes import API_ROUTES

        for method, path, handler_ref, desc in API_ROUTES:
            if handler_ref.startswith("."):
                name = handler_ref[1:]
                handler = getattr(self, name, None)
                if not handler:
                    # ApiHandlers mixin methods use a `_` prefix (e.g. `_health`);
                    # route refs may omit it — try the prefixed form before skipping.
                    handler = getattr(self, f"_{name}", None)
                if not handler:
                    logger.debug("route handler not found (not yet implemented): %s", handler_ref)
                    continue
            else:
                try:
                    mod_path, func_name = handler_ref.rsplit(".", 1)
                    mod = importlib.import_module(mod_path)
                    handler = getattr(mod, func_name)
                except Exception as e:
                    logger.warning("route import failed: %s: %s", handler_ref, e)
                    continue
            self.register_route(method, path, handler, desc)

        # SSE bridge activation
        try:
            from l4.sse.sse_bridge import ensure_active
            ensure_active()
        except Exception as e:
            logger.warning("sse activation: %s", e)

    # ── Route matching ───────────────────────────────────────────────────

    def _match_route(self, method: str, path: str) -> tuple[Callable, dict]:
        """Find matching route. Returns (handler, path_params).

        Matching priority (fixes the trailing-slash prefix hijack where a
        wildcard like ``/api/skills/`` captured explicit sub-paths such as
        ``/api/skills/permissions``):

          1. Exact match (``path == r.path``).
          2. ``{param}`` pattern match (e.g. ``/api/v2/discussion/{session_id}``).
          3. Legacy trailing-slash prefix fallback (``/api/card/`` →
             ``/api/card/<id>``) — only when nothing above matched.

        Exact and ``{param}`` patterns are each scanned in registration order,
        but exact matches are always preferred over ``{param}`` so a concrete
        sub-path (``/api/v2/skills/permissions``) never falls into a parameter
        route (``/api/v2/skills/{name}``).

        Placeholder names mirror the handler keyword arguments (e.g.
        ``{name}`` → ``handle_skills_get(body, name="")``); they are NOT a
        generic ``id`` — see _match_param_pattern for segment-wise capture.
        """
        # Pass 0: O(1) exact-match index (rebuilt when the route table changes)
        if len(self._routes) != self._index_route_count:
            self._rebuild_exact_index()
        hit = self._exact_index.get((method, path))
        if hit is not None:
            return hit
        # Pass 1b: {param} patterns only
        for r in self._routes:
            if r.method != method or r.path.endswith("/") or "{" not in r.path:
                continue
            params = self._match_param_pattern(r.path, path)
            if params is not None:
                return r.handler, params
        # Pass 2: legacy trailing-slash prefix fallback
        for r in self._routes:
            if r.method != method or not r.path.endswith("/"):
                continue
            prefix = r.path.rstrip("/")
            if path.startswith(prefix + "/"):
                remainder = path[len(prefix) + 1:]
                if remainder == "":
                    return r.handler, {"id": ""}
                if "/" not in remainder:
                    return r.handler, {"id": remainder}
        return self._not_found, {}

    @staticmethod
    def _match_param_pattern(pattern: str, path: str) -> dict | None:
        """Match a ``{param}`` path pattern against a concrete path.

        Returns the extracted params dict, or None when the path does not
        match the pattern.  Segment-wise comparison — ``{name}`` captures a
        single path segment.

        Example: ``/api/v2/discussion/{id}`` vs ``/api/v2/discussion/abc``
                 → ``{"id": "abc"}``
        """
        p_segs = pattern.strip("/").split("/")
        r_segs = path.strip("/").split("/")
        if len(p_segs) != len(r_segs):
            return None
        params: dict[str, str] = {}
        for p, r in zip(p_segs, r_segs, strict=False):
            if p.startswith("{") and p.endswith("}"):
                params[p[1:-1]] = r
            elif p != r:
                return None
        return params

    @staticmethod
    def _route_dispatch(handler: Callable, data: dict,
                        query: dict | None, params: dict,
                        user_id: str) -> dict:
        """Build the handler body dict and invoke the route handler.

        Merge order guarantees the URL path is the authoritative resource
        identifier: query params are merged FIRST, then path params (and the
        legacy ``_id`` key) so a same-named query string can never override
        the path value (parameter confusion fix).

        Keyword binding is decided via ``inspect.signature`` instead of a
        runtime ``TypeError`` probe — a probe would mask genuine handler
        errors and re-run side effects on the second invocation.  Two
        conventions are supported:
          - body-first handlers: ``handle_skills_get(body, name="")``
          - name-first handlers: ``handle_discussion_get(session_id="")``
        """
        body = dict(data)
        if query:
            body.update(query)
        if params.get("id"):
            body["_id"] = params["id"]
        body.update(params)
        body["_user_id"] = user_id
        sig_params = _handler_params(handler)
        if sig_params is None:
            return handler(body)
        first = next(iter(sig_params.values()), None)
        kwargs = {k: v for k, v in params.items() if k in sig_params}
        if not kwargs:
            return handler(body)
        if first and first.name in params:
            # name-first handler (e.g. handle_discussion_get(session_id=""))
            return handler(**kwargs)
        # body-first handler (e.g. handle_skills_get(body, name=""))
        return handler(body, **kwargs)

    def _not_found(self, body: dict) -> dict:
        return {"error": "not found"}

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> dict:
        """Start the API server in a background thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("API gateway started on %s:%d", self.host, self.port)
        # WebSocket bridge on its own port (bidirectional realtime channel)
        try:
            from l4.ws.ws_bridge import start_server as _start_ws

            _start_ws()
        except Exception as e:
            logger.warning("API gateway: ws bridge start failed: %s", e)
        # RPC server on its own port (distributed/remote method invocation)
        try:
            from l4.rpc.server import get_server as _get_rpc_server

            _get_rpc_server()
        except Exception as e:
            logger.warning("API gateway: rpc server start failed: %s", e)
        return {"success": True, "host": self.host, "port": self.port}

    def stop(self) -> None:
        """Stop the HTTP server and release the bound port."""
        if self._server:
            self._server.shutdown()

    # ── HTTP server (MiddlewareChain integrated) ─────────────────────────

    def _run(self) -> None:
        import http.server
        import urllib.parse

        class _Handler(http.server.BaseHTTPRequestHandler):
            """_Handler — _ handler record (gateway)."""
            gateway: ApiGateway | None = None  # set after class definition (class-body scoping)

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

            def _build_request(self, method: str, path: str,
                               body: dict | None = None) -> Request:
                """Build a Request object from HTTP headers + body."""
                parsed = urllib.parse.urlparse(path)
                query = urllib.parse.parse_qs(parsed.query)
                flat_query = {k: v[0] if len(v) == 1 else v
                              for k, v in query.items()}
                return Request(
                    method=method,
                    path=parsed.path.rstrip("/"),
                    headers=dict(self.headers),
                    body=body or {},
                    query=flat_query,
                    raw_body=self.rfile.read(
                        int(self.headers.get("Content-Length", 0))
                    ) if body is None else b"",
                    user_id=self._user_id(),
                )

            def _handle_via_middleware(self, method: str) -> None:
                """Route request through MiddlewareChain (GET/POST/DELETE)."""
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
                    return gw._route_dispatch(
                        handler, r.body, r.query, params, r.user_id)

                t0 = time.time()
                resp = gw._middleware.handle(req, route_handler)
                latency_ms = round((time.time() - t0) * 1000, 2)
                self._json(resp.data, resp.status)
                self._expose_request_stats(method, path, resp, req, latency_ms)

            def _expose_request_stats(self, method: str, path: str,
                                      resp: Any, req: Request,
                                      latency_ms: float) -> None:
                """Expose request timing to the monitoring center (MonitorBus)
                and the statistics center (StatsCenter) — api.request.* metrics
                and stats.api.request events (consumed by /api/v2/stats/live).
                """
                try:
                    from l3.bus.monitor_bus import MonitorEvent
                    from l3.bus.monitor_bus import get_bus as _mb2
                    _mb2().emit(MonitorEvent(
                        type="stats.api.request", source="api_gateway",
                        severity="info",
                        message=f"{method} {path} -> {getattr(resp, 'status', '?')}",
                        data={"method": method, "path": path,
                              "status": getattr(resp, "status", 0),
                              "latency_ms": latency_ms,
                              "user_id": req.user_id},
                    ))
                except Exception:
                    logger.debug("api_gateway: monitor emit failed")
                try:
                    from l3.services.stats_center import MetricPoint
                    from l3.services.stats_center import get_center as _sc2
                    _ts = time.time()
                    _tags = {"endpoint": path, "method": method,
                             "status": str(getattr(resp, "status", 0))}
                    # Phase E: tag security-domain requests so api.request.*
                    # metrics can be sliced by domain.
                    if path.startswith("/api/v2/security"):
                        _tags["domain"] = "security"
                    _sc2().ingest(MetricPoint(name="api.request.latency", value=latency_ms,
                                              tags=_tags, timestamp=_ts, metric_type="gauge"))
                    _sc2().ingest(MetricPoint(name="api.request.count", value=1.0,
                                              tags=_tags, timestamp=_ts, metric_type="counter"))
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

        _Handler.gateway = self

        try:
            addr = (self.host, self.port)
            self._server = http.server.ThreadingHTTPServer(addr, _Handler)
            # port=0 (ephemeral) — backfill the OS-assigned port so callers
            # can connect without a fixed-port collision race.
            if self.port == 0:
                self.port = int(self._server.server_address[1])
            self._server.serve_forever()
        except OSError as e:
            logger.error("API gateway failed to start: %s", e)
        except Exception as e:
            logger.error("API gateway error: %s", e)


# ── Module-level singleton ──────────────────────────────────────────────────

_gateway: ApiGateway | None = None
_gateway_lock = threading.Lock()


def start_api(host: str = API_GATEWAY_HOST, port: int = API_GATEWAY_PORT,
              auth_token: str = "") -> ApiGateway:
    """Start the module-level gateway singleton and return it."""
    global _gateway
    if _gateway is None:
        with _gateway_lock:
            if _gateway is None:
                _gateway = ApiGateway(host, port, auth_token)
                _gateway.start()
    return _gateway


def stop_api() -> None:
    """Stop the module-level gateway singleton and drop the reference."""
    global _gateway
    if _gateway:
        _gateway.stop()
    _gateway = None


def get_gateway() -> ApiGateway | None:
    return _gateway


# ── YAML route loader ───────────────────────────────────────────────────────

def load_routes_from_yaml(routes_cfg: list[dict]) -> dict:
    """Load API routes from a list of route dicts (from praxis.yaml api.routes)."""
    gw = _gateway
    if not gw:
        return {"success": False, "error": "API gateway not started"}

    loaded = 0
    errors = []
    for entry in (routes_cfg or []):
        method = entry.get("method", "GET").upper()
        path = entry.get("path", "")
        handler_path = entry.get("handler", "")
        description = entry.get("description", "")
        if not path or not handler_path:
            errors.append(f"route missing path or handler: {entry}")
            continue
        try:
            handler = _resolve_handler(handler_path)
            gw.register_route(method, path, handler, description)
            loaded += 1
        except Exception as e:
            errors.append(f"route {method} {path}: {e}")

    if errors:
        logger.warning("load_routes: %d loaded, %d errors: %s",
                       loaded, len(errors), errors)
    return {"success": True, "loaded": loaded, "errors": errors}


def _resolve_handler(path: str) -> Callable:
    """Resolve 'module.attr:subattr' to a callable."""
    module_path, _, attr_path = path.partition(":")
    if not attr_path:
        raise ValueError(f"handler path must contain ':' — got '{path}'")
    import importlib
    mod = importlib.import_module(module_path)
    parts = attr_path.split(".")
    obj = mod
    for part in parts:
        obj = getattr(obj, part)
        if callable(obj):
            return obj
    if callable(obj):
        return obj
    raise ValueError(f"'{attr_path}' in {module_path} is not callable")


if __name__ == "__main__":
    start_api()
