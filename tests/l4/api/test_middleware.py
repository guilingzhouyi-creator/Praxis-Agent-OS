"""API middleware tests — Request, Response, MiddlewareChain, built-in middleware."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestRequest:
    def test_create_request(self):
        from l4.api.api_middleware import Request
        req = Request(method="GET", path="/api/health", headers={"Host": "localhost"})
        assert req.method == "GET"
        assert req.path == "/api/health"


class TestResponse:
    def test_ok_response(self):
        from l4.api.api_middleware import Response
        r = Response.ok({"status": "ok"})
        assert r.status == 200

    def test_error_response(self):
        from l4.api.api_middleware import Response
        r = Response.error("bad request", status=400)
        assert r.status == 400

    def test_json_response(self):
        from l4.api.api_middleware import Response
        r = Response.json({"data": [1, 2]}, status=201)
        assert r.status == 201


class TestMiddlewareChain:
    def test_empty_chain_ok(self):
        from l4.api.api_middleware import MiddlewareChain, Request
        chain = MiddlewareChain()
        req = Request(method="GET", path="/")
        result = chain.handle(req, handler=lambda r: {"ok": True})
        assert result.status == 200

    def test_use_middleware(self):
        from l4.api.api_middleware import Middleware, MiddlewareChain, Request, Response

        class TestMw(Middleware):
            def process(self, request):
                return Response.ok({"mw": "ran"})

        chain = MiddlewareChain()
        chain.use(TestMw())
        req = Request(method="GET", path="/")
        result = chain.handle(req, handler=lambda r: {"ok": True})
        assert result.status == 200
        assert result.data.get("mw") == "ran"

    def test_middleware_aborts_chain(self):
        from l4.api.api_middleware import Middleware, MiddlewareChain, Request, Response

        class AbortMw(Middleware):
            def process(self, request):
                return Response.error("blocked", status=403)

        chain = MiddlewareChain()
        chain.use(AbortMw())
        req = Request(method="GET", path="/")
        result = chain.handle(req, handler=lambda r: {"ok": True})
        assert result.status == 403


class TestCORSMiddleware:
    def test_adds_cors_headers(self):
        from l4.api.api_middleware import CORSMiddleware, Request, Response
        mw = CORSMiddleware(origin="*")
        req = Request(method="OPTIONS", path="/test", headers={})
        resp = Response.ok({})
        result = mw.process_response(resp)
        assert result.headers.get("Access-Control-Allow-Origin") == "*"
