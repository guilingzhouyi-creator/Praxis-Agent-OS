"""API Gateway — HTTP interface with MiddlewareChain + Route dispatching.

Architecture:
  HTTPServer → _Handler (parse) → MiddlewareChain (process) → ApiHandlers (business)

Usage:
  from l4.api.api_gateway import start_api
  start_api()  # default port from kernel.params
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from l1.kernel.params.api import (
    API_CORS_ALLOW_HEADERS,
    API_CORS_ALLOW_METHODS,
    API_CORS_ORIGIN,
    API_GATEWAY_HOST,
    API_GATEWAY_PORT,
    ENV_API_TOKEN,
)
from l4.api.api_handler import ApiGatewayHandler, _auth_ok  # noqa: F401 — _auth_ok re-exported for tests
from l4.api.api_middleware import (
    CORSMiddleware,
    LocaleMiddleware,
    MiddlewareChain,
)
from l4.api_handlers import ApiHandlers

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

    def __init__(self, host: str = API_GATEWAY_HOST, port: int = API_GATEWAY_PORT, auth_token: str = ""):
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
        self._middleware = MiddlewareChain(
            [
                CORSMiddleware(
                    origin=API_CORS_ORIGIN,
                    methods=API_CORS_ALLOW_METHODS,
                    headers=API_CORS_ALLOW_HEADERS,
                ),
                LocaleMiddleware(),
            ]
        )

        self._register_defaults()

    # ── Route registration ───────────────────────────────────────────────

    def register_route(self, method: str, path: str, handler: Callable, description: str = "") -> None:
        """Register a new API route."""
        self._routes.append(
            Route(
                method=method,
                path=path,
                handler=handler,
                description=description,
            )
        )
        self._index_route_count = -1  # exact index needs a lazy rebuild

    def _rebuild_exact_index(self) -> None:
        """Rebuild the (method, path) → handler index from ``_routes``."""
        self._exact_index = {
            (r.method, r.path): (r.handler, {}) for r in self._routes if not r.path.endswith("/") and "{" not in r.path
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
                remainder = path[len(prefix) + 1 :]
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
    def _route_dispatch(handler: Callable, data: dict, query: dict | None, params: dict, user_id: str) -> dict:
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

        ApiGatewayHandler.gateway = self

        try:
            addr = (self.host, self.port)
            self._server = http.server.ThreadingHTTPServer(addr, ApiGatewayHandler)
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


def start_api(host: str = API_GATEWAY_HOST, port: int = API_GATEWAY_PORT, auth_token: str = "") -> ApiGateway:
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
    for entry in routes_cfg or []:
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
        logger.warning("load_routes: %d loaded, %d errors: %s", loaded, len(errors), errors)
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
