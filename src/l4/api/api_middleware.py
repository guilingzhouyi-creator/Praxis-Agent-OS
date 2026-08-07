"""API Middleware chain — onion-model request processing pipeline.

Each middleware wraps the next, forming a chain:
  Request → [CORS] → [Auth] → [Locale] → [BodyParser] → Handler → Response

Middleware can:
  - Inspect/modify the request before it reaches the handler
  - Inspect/modify the response after the handler returns
  - Short-circuit the chain by returning a response early

Built-in middleware provided here:
  - LocaleMiddleware   — sets I18nPort locale from Accept-Language / ?locale=
  - CORSMiddleware     — handles CORS headers (extracted from api_gateway)
  - BodyParserMiddleware — parses request body with size limits
  - RequestLogMiddleware — logs incoming requests
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from l1.kernel.discovery import get_service_limit
from l1.kernel.params.api import API_MIDDLEWARE_TIMEOUT, I18N_DEFAULT_LOCALE

logger = logging.getLogger(__name__)


# ── Request / Response types ──


class Request:
    """Immutable request object flowing through middleware chain."""

    def __init__(self, method: str = "GET", path: str = "",
                 headers: dict | None = None,
                 body: dict | None = None,
                 query: dict | None = None,
                 raw_body: bytes | None = None,
                 **kwargs: Any) -> None:
        self.method = method.upper()
        self.path = path
        self.headers = headers or {}
        self.body = body or {}
        self.query = query or {}
        self.raw_body = raw_body or b""
        self.locale: str = I18N_DEFAULT_LOCALE
        self.user_id: str = ""
        self.params: dict = {}           # route path params
        self.deadline: float = 0.0       # middleware-set execution deadline marker
        self._extra: dict = kwargs

    def __getattr__(self, name: str) -> Any:
        return self._extra.get(name)


class Response:
    """Response object flowing back through middleware chain."""

    def __init__(self, data: Any = None, status: int = 200,
                 headers: dict | None = None) -> None:
        self.data = data if data is not None else {}
        self.status = status
        self.headers = headers or {}

    @staticmethod
    def ok(data: Any = None) -> Response:
        """Build a 200 response carrying the given data payload."""
        return Response(data=data or {}, status=200)

    @staticmethod
    def error(msg: str, status: int = 400) -> Response:
        """Build an error response with the given message and status code."""
        return Response(data={"error": msg}, status=status)

    @staticmethod
    def json(data: Any, status: int = 200) -> Response:
        """Build a JSON-typed response with the given data and status code."""
        return Response(data=data, status=status,
                        headers={"Content-Type": "application/json"})


# ── Middleware base ──


class Middleware:
    """Base middleware — override process() or process_response()."""

    def process(self, request: Request) -> Request | Response | None:
        """Pre-process request. Return Response to short-circuit chain."""
        return request

    def process_response(self, response: Response) -> Response:
        """Post-process response before sending."""
        return response


# ── MiddlewareChain ──


class MiddlewareChain:
    """Onion-model middleware chain.

    Usage:
        chain = MiddlewareChain([
            CORSMiddleware(),
            LocaleMiddleware(),
        ])
        resp = chain.handle(request, handler_fn)
    """

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self._middlewares = middlewares or []

    def use(self, mw: Middleware) -> MiddlewareChain:
        """Append a middleware to the chain (builder pattern)."""
        self._middlewares.append(mw)
        return self

    def handle(self, request: Request, handler: Any) -> Response:
        """Run request through all middlewares, then handler, then response middlewares."""
        # Forward pass
        req = request
        for mw in self._middlewares:
            result = mw.process(req)
            if isinstance(result, Response):
                # Short-circuit
                return self._reverse_process_response(result)
            req = result or req

        # Handler
        try:
            data = handler(req)
            if isinstance(data, Response):
                resp = data
            elif isinstance(data, dict):
                resp = Response.json(data)
            else:
                resp = Response.ok(data)
        except Exception as e:
            logger.exception("handler error")
            resp = Response.error(str(e), status=500)

        # Backward pass
        return self._reverse_process_response(resp)

    def _reverse_process_response(self, resp: Response) -> Response:
        for mw in reversed(self._middlewares):
            resp = mw.process_response(resp)
        return resp


# ── LocaleMiddleware ──


def _parse_accept_language(header: str) -> str | None:
    """Parse Accept-Language header, return the highest-priority known locale.

    Handles forms like:
      "zh-CN,zh;q=0.9,en;q=0.8"  → "zh-CN"
      "en-US,en;q=0.5"           → "en"
    """
    if not header:
        return None
    parts = header.split(",")
    candidates: list[tuple[float, str]] = []
    for part in parts:
        part = part.strip()
        if ";" in part:
            lang, q = part.split(";", 1)
            try:
                q_val = float(q.replace("q=", "").strip())
            except (ValueError, IndexError):
                q_val = 1.0
        else:
            lang = part
            q_val = 1.0
        candidates.append((q_val, lang.strip()))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1] if candidates else None


_KNOWN_LOCALES = {"en", "zh-CN", "zh", "ja", "ko", "de", "fr", "es"}


def _normalize_locale(raw: str) -> str:
    """Normalize a locale string to a known form, falling back to 'en'."""
    raw = raw.replace("-", "_")
    if raw in _KNOWN_LOCALES or raw.split("_")[0] in _KNOWN_LOCALES:
        # Return the canonical form for known locales
        for known in _KNOWN_LOCALES:
            if raw.startswith(known.split("-")[0]):
                return known
    return "en"


class LocaleMiddleware(Middleware):
    """Sets request.locale and I18nPort locale from query param or Accept-Language.

    Priority (highest first):
      1. ?locale= query parameter
      2. Accept-Language request header
      3. I18nPort default locale
    """

    def process(self, request: Request) -> Request:
        """Resolve and apply the request locale from query, header, or I18nPort default."""
        raw = (
            request.query.get("locale", "")
            or _parse_accept_language(request.headers.get("Accept-Language", ""))
            or ""
        )
        if raw:
            locale = _normalize_locale(raw)
        else:
            try:
                from l1.kernel.ports import get_port as _gp
                locale = _gp("i18n").get_locale()
            except Exception:
                logger.debug("api_middleware: get_locale failed, falling back to 'en'")
                locale = "en"

        request.locale = locale

        # Propagate to I18nPort for downstream handlers
        try:
            from l1.kernel.ports import get_port as _gp
            _gp("i18n").set_locale(locale)
        except Exception:
            logger.debug("api_middleware: locale set failed")

        return request


# ── CORSMiddleware ──


class CORSMiddleware(Middleware):
    """Adds CORS headers to every response."""

    def __init__(self, origin: str = "*",
                 methods: str = "GET,POST,DELETE,OPTIONS",
                 headers: str = "Content-Type,Authorization") -> None:
        self._origin = origin
        self._methods = methods
        self._headers = headers

    def process_response(self, response: Response) -> Response:
        response.headers.setdefault("Access-Control-Allow-Origin", self._origin)
        response.headers.setdefault("Access-Control-Allow-Methods", self._methods)
        response.headers.setdefault("Access-Control-Allow-Headers", self._headers)
        return response


# ── BodyParserMiddleware ──


class BodyParserMiddleware(Middleware):
    """Parse JSON body from raw bytes, enforcing size limits."""

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        self._max_bytes = max_bytes

    def process(self, request: Request) -> Request | Response:
        """Parse the JSON body, enforcing the size limit; return error response on failure."""
        if not request.raw_body:
            return request
        if len(request.raw_body) > self._max_bytes:
            return Response.error(f"body too large (max {self._max_bytes} bytes)", 413)
        try:
            request.body = json.loads(request.raw_body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            return Response.error(f"invalid JSON: {e}", 400)
        return request


# ── RequestLogMiddleware ──


_request_local = threading.local()


class RequestLogMiddleware(Middleware):
    """Log request method, path, status, and duration.

    Uses ``threading.local()`` to associate each request with its start time
    across the ``process()`` → handler → ``process_response()`` boundary.
    """

    def process(self, request: Request) -> Request:
        """Record the request start time and method in thread-local storage."""
        _request_local.start_time = time.time()
        _request_local.method = request.method
        return request

    def process_response(self, response: Response) -> Response:
        """Log method, status, and elapsed time for the completed request."""
        started = getattr(_request_local, "start_time", None)
        if started:
            elapsed = time.time() - started
            method = getattr(_request_local, "method", "?")
            logger.info("API %s → %s (%.0fms)", method, response.status, elapsed * 1000)
        return response


# ── TimeoutMiddleware ──


class TimeoutMiddleware(Middleware):
    """Enforce a maximum processing time for requests.

    Note: actual enforcement requires the WorkerPort to support cancellation.
    This middleware sets a deadline marker for observability.
    """

    def __init__(self, timeout: float | None = None) -> None:
        # Declarative override via config/discovery/service_limits.yaml,
        # params constant as fallback (AGENTS.md three-layer config).
        if timeout is None:
            timeout = get_service_limit("api_middleware_timeout", API_MIDDLEWARE_TIMEOUT)
        self._timeout = timeout

    def process(self, request: Request) -> Request:
        """Set the request deadline marker to now plus the configured timeout."""
        request.deadline = time.time() + self._timeout
        return request
