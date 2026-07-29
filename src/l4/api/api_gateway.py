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
from dataclasses import dataclass, field
from typing import Any, Callable

from l1.kernel.params.api import (
    ENV_API_TOKEN,
    API_GATEWAY_DEFAULT_PORT,
    API_CORS_ORIGIN,
    API_CORS_ALLOW_METHODS,
    API_CORS_ALLOW_HEADERS,
    API_GATEWAY_PORT,
    API_GATEWAY_HOST,
    API_MAX_BODY_BYTES,
    API_GATEWAY_QUEUE_TIMEOUT,
)
from l4.api_handlers import ApiHandlers
from l4.api.api_middleware import (
    MiddlewareChain, LocaleMiddleware, CORSMiddleware,
    Request, Response,
)

logger = logging.getLogger(__name__)


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

    def _register_defaults(self) -> None:
        """Load all routes from centralized api_routes.py + external modules."""
        import importlib
        from .api.api_routes import API_ROUTES

        for method, path, handler_ref, desc in API_ROUTES:
            if handler_ref.startswith("."):
                handler = getattr(self, handler_ref[1:], None)
                if not handler:
                    logger.warning("route handler not found: %s", handler_ref)
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
        """Find matching route. Returns (handler, path_params)."""
        for r in self._routes:
            if r.method != method:
                continue
            if r.path.endswith("/"):
                prefix = r.path.rstrip("/")
                if path.startswith(prefix + "/"):
                    remainder = path[len(prefix) + 1:]
                    if remainder == "":
                        return r.handler, {"id": ""}
                    if "/" not in remainder:
                        return r.handler, {"id": remainder}
                    continue
            elif path == r.path:
                return r.handler, {}
        return self._not_found, {}

    def _not_found(self, body: dict) -> dict:
        return {"error": "not found"}

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> dict:
        """Start the API server in a background thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("API gateway started on %s:%d", self.host, self.port)
        return {"success": True, "host": self.host, "port": self.port}

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    # ── HTTP server (MiddlewareChain integrated) ─────────────────────────

    def _run(self) -> None:
        import http.server
        import urllib.parse

        gateway = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            gateway = gateway

            def log_message(self, fmt, *args):
                pass  # Suppress default http.server logging

            def _auth_ok(self) -> bool:
                import hmac
                if not self.gateway.auth_token:
                    return True
                received = self.headers.get("Authorization", "").replace("Bearer ", "")
                if len(received) != len(self.gateway.auth_token):
                    return False
                return hmac.compare_digest(received, self.gateway.auth_token)

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

                # SSE special handling: long-lived connection
                if method == "GET" and path == "/api/events":
                    self._do_sse()
                    return

                # Read body for POST/DELETE (must happen once, before build_request)
                body = self._read_body() if method in ("POST", "DELETE") else {}
                req = self._build_request(method, self.path, body=body)
                handler, params = self.gateway._match_route(method, path)
                req.params = params

                def route_handler(r: Request) -> dict:
                    data = dict(r.body)
                    if params.get("id"):
                        data["_id"] = params["id"]
                    data["_user_id"] = r.user_id
                    # Merge query params for GET
                    if r.method == "GET":
                        data.update(r.query)
                    return handler(data)

                resp = self.gateway._middleware.handle(req, route_handler)
                self._json(resp.data, resp.status)

            def _do_sse(self) -> None:
                """Handle SSE /api/events streaming connection."""
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
                self.end_headers()
                try:
                    from l4.sse.sse_bridge import subscribe, unsubscribe
                    import queue as _queue
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
                    pass
                except Exception:
                    logger.debug("api_gateway: sse handler failed")
                finally:
                    try:
                        from l4.sse.sse_bridge import unsubscribe as _unsub
                        _unsub(client.get("client_id", ""))
                    except Exception:
                        logger.debug("api_gateway: sse unsubscribe failed")

            def do_POST(self):
                self._handle_via_middleware("POST")

            def do_GET(self):
                self._handle_via_middleware("GET")

            def do_DELETE(self):
                self._handle_via_middleware("DELETE")

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
                self.send_header("Access-Control-Allow-Methods", API_CORS_ALLOW_METHODS)
                self.send_header("Access-Control-Allow-Headers", API_CORS_ALLOW_HEADERS)
                self.end_headers()

        try:
            addr = (self.host, self.port)
            self._server = http.server.ThreadingHTTPServer(addr, _Handler)
            self._server.serve_forever()
        except OSError as e:
            logger.error("API gateway failed to start: %s", e)
        except Exception as e:
            logger.error("API gateway error: %s", e)


# ── Module-level singleton ──────────────────────────────────────────────────

_gateway: ApiGateway | None = None


def start_api(host: str = API_GATEWAY_HOST, port: int = API_GATEWAY_PORT,
              auth_token: str = "") -> ApiGateway:
    global _gateway
    if _gateway is None:
        _gateway = ApiGateway(host, port, auth_token)
        _gateway.start()
    return _gateway


def stop_api() -> None:
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


def _resolve_handler(path: str) -> callable:
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
