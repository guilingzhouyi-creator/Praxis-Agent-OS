"""API Gateway 集成测试 — HTTP route→handler→middleware→response。"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestAPIGatewayInit:
    def test_create_instance(self):
        from l4.api.api_gateway import ApiGateway
        gw = ApiGateway()
        assert gw is not None
        assert hasattr(gw, 'register_route')
        assert hasattr(gw, '_routes')

    def test_default_host_port(self):
        from l1.kernel.params.api import API_GATEWAY_HOST, API_GATEWAY_PORT
        assert API_GATEWAY_HOST == "127.0.0.1"
        assert API_GATEWAY_PORT == 8080


class TestAPIRouteRegistration:
    def test_register_route(self):
        from l4.api.api_gateway import ApiGateway
        gw = ApiGateway()
        gw._routes.clear()
        gw.register_route("GET", "/api/health", lambda b: {"status": "ok"}, "health check")
        assert len(gw._routes) == 1

    def test_register_multiple_routes(self):
        from l4.api.api_gateway import ApiGateway
        gw = ApiGateway()
        gw._routes.clear()
        routes = [("GET", "/api/a"), ("POST", "/api/b"), ("GET", "/api/c")]
        for method, path in routes:
            gw.register_route(method, path, lambda b: {}, "test")
        assert len(gw._routes) == 3


class TestAPIRoutesInit:
    def test_api_routes_importable(self):
        from l4.api.api_routes import API_ROUTES
        assert isinstance(API_ROUTES, list)
        assert len(API_ROUTES) >= 100

    def test_route_structure(self):
        from l4.api.api_routes import API_ROUTES
        for route in API_ROUTES[:10]:
            assert len(route) >= 3
            assert route[0] in ("GET", "POST", "PUT", "DELETE", "PATCH")
            assert route[1].startswith("/api/")


class TestMiddlewareIntegration:
    def test_middleware_chain_importable(self):
        from l4.api.api_middleware import MiddlewareChain
        chain = MiddlewareChain()
        assert chain is not None

    def test_cors_middleware(self):
        from l1.kernel.params.api import API_CORS_ORIGIN
        from l4.api.api_middleware import CORSMiddleware
        mw = CORSMiddleware()
        assert mw is not None
        assert API_CORS_ORIGIN == "*"


class TestHttpParamLink:
    """End-to-end HTTP link: request → build_request → match_route → route_handler.

    Regression for the parameter-confusion fix — a same-named query param
    must never override the path resource id through the REAL HTTP chain
    (not just the extracted _route_dispatch helper).
    """

    def test_http_query_cannot_override_path(self):
        import http.client
        import json

        from l4.api.api_gateway import ApiGateway

        # port=0 → OS-assigned ephemeral port: no fixed-port collision race
        # between parallel workers. Readiness is polled instead of a blind
        # sleep, so a loaded CI runner cannot hit a not-yet-bound server.
        gw = ApiGateway(port=0, auth_token="")
        gw._routes.clear()
        gw.register_route(
            "GET", "/api/v2/card/{id}",
            lambda b: {"ok": True, "_id": b.get("_id")},
            "get card (param-confusion regression)")
        gw.start()
        try:
            deadline = time.time() + 5.0
            while True:
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", gw.port, timeout=1)
                    conn.request("GET", "/api/v2/card/abc?_id=evil")
                    resp = conn.getresponse()
                    data = json.loads(resp.read().decode())
                    conn.close()
                    break
                except (ConnectionRefusedError, ConnectionResetError, OSError):
                    if time.time() > deadline:
                        raise
                    time.sleep(0.05)
            assert data.get("ok") is True
            assert data.get("_id") == "abc", (
                f"path id must win over query, got {data.get('_id')!r}")
        finally:
            gw.stop()
