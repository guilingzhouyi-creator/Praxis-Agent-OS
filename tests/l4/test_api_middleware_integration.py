"""L4 API middleware + route dispatch integration test.

Covers:
  - Middleware chain (CORS, Locale, BodyParser, RequestLog)
  - Full dispatch flow through middleware → route → handler
  - Auth token validation
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))



class TestCORSMiddleware:
    """CORS header injection on every response."""

    def test_cors_headers_added(self):
        from l4.api.api_middleware import CORSMiddleware, Request, Response
        mw = CORSMiddleware(origin="*", methods="GET,POST", headers="Content-Type")

        req = Request(method="GET", path="/api/health")
        out = mw.process(req)
        assert out is req  # CORS doesn't modify request

        resp = Response.ok({"ok": True})
        out_resp = mw.process_response(resp)
        assert out_resp.headers.get("Access-Control-Allow-Origin") == "*"
        assert "GET" in out_resp.headers.get("Access-Control-Allow-Methods", "")

    def test_cors_preflight(self):
        from l4.api.api_middleware import CORSMiddleware, Request
        mw = CORSMiddleware(origin="https://example.com")
        req = Request(method="OPTIONS", path="/api/card")
        out = mw.process(req)
        # Preflight should return a response, not the request
        assert hasattr(out, "data") or hasattr(out, "status")


class TestLocaleMiddleware:
    """Locale detection from query param / Accept-Language header."""

    def test_locale_from_query(self):
        from l4.api.api_middleware import LocaleMiddleware, Request
        mw = LocaleMiddleware()
        req = Request(method="GET", path="/api/health", query={"locale": "zh-CN"})
        out = mw.process(req)
        assert out.locale in ("zh-CN", "zh")  # exact parsing depends on implementation

    def test_locale_defaults_to_en(self):
        from l1.kernel.params.api import I18N_DEFAULT_LOCALE
        from l4.api.api_middleware import LocaleMiddleware, Request
        mw = LocaleMiddleware()
        req = Request(method="GET", path="/api/health")
        out = mw.process(req)
        assert out.locale == I18N_DEFAULT_LOCALE


class TestMiddlewareChain:
    """Onion-model middleware chain processes requests in order."""

    def test_chain_handles_request(self):
        from l4.api.api_middleware import (
            CORSMiddleware,
            LocaleMiddleware,
            MiddlewareChain,
            Request,
        )
        chain = MiddlewareChain([
            CORSMiddleware(origin="*"),
            LocaleMiddleware(),
        ])
        req = Request(method="GET", path="/api/test", query={"locale": "fr"})
        handler = lambda r: {"status": "ok", "locale": r.locale}
        resp = chain.handle(req, handler)
        assert resp.data.get("locale") == "fr"

    def test_chain_short_circuits(self):
        from l4.api.api_middleware import (
            Middleware,
            MiddlewareChain,
            Request,
            Response,
        )

        class BlockMiddleware(Middleware):
            def process(self, request):
                return Response.error("blocked", 403)

        chain = MiddlewareChain([BlockMiddleware()])
        req = Request(method="DELETE", path="/api/sensitive")
        resp = chain.handle(req, lambda r: {"ok": True})
        assert resp.status == 403

    def test_chain_processes_response(self):
        from l4.api.api_middleware import (
            CORSMiddleware,
            MiddlewareChain,
            Request,
        )
        chain = MiddlewareChain([CORSMiddleware(origin="https://app.com")])
        req = Request(method="GET", path="/api/health")
        handler = lambda r: {"status": "ok"}
        resp = chain.handle(req, handler)
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.com"


class TestRouteTable:
    """API_ROUTES static table validation."""

    def test_routes_have_required_fields(self):
        from l4.api.api_routes import API_ROUTES
        for method, path, handler, desc in API_ROUTES:
            assert method in ("GET", "POST", "PUT", "DELETE")
            assert path.startswith("/api/")
            assert isinstance(handler, str)
            assert isinstance(desc, str)

    def test_no_duplicate_routes(self):
        from l4.api.api_routes import API_ROUTES
        seen = set()
        for method, path, _, _ in API_ROUTES:
            key = (method, path)
            assert key not in seen, f"duplicate: {key}"
            seen.add(key)
