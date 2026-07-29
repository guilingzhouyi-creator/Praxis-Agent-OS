"""API Gateway 集成测试 — HTTP route→handler→middleware→response。"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestAPIGatewayInit:
    def test_create_instance(self):
        from l4.api_gateway import ApiGateway
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
        from l4.api_gateway import ApiGateway
        gw = ApiGateway()
        gw._routes.clear()
        gw.register_route("GET", "/api/health", lambda b: {"status": "ok"}, "health check")
        assert len(gw._routes) == 1

    def test_register_multiple_routes(self):
        from l4.api_gateway import ApiGateway
        gw = ApiGateway()
        gw._routes.clear()
        routes = [("GET", "/api/a"), ("POST", "/api/b"), ("GET", "/api/c")]
        for method, path in routes:
            gw.register_route(method, path, lambda b: {}, "test")
        assert len(gw._routes) == 3


class TestAPIRoutesInit:
    def test_api_routes_importable(self):
        from l4.api_routes import API_ROUTES
        assert isinstance(API_ROUTES, list)
        assert len(API_ROUTES) >= 100

    def test_route_structure(self):
        from l4.api_routes import API_ROUTES
        for route in API_ROUTES[:10]:
            assert len(route) >= 3
            assert route[0] in ("GET", "POST", "PUT", "DELETE", "PATCH")
            assert route[1].startswith("/api/")


class TestMiddlewareIntegration:
    def test_middleware_chain_importable(self):
        from l4.api_middleware import MiddlewareChain, LocaleMiddleware, CORSMiddleware
        chain = MiddlewareChain()
        assert chain is not None

    def test_cors_middleware(self):
        from l4.api_middleware import CORSMiddleware
        from l1.kernel.params.api import API_CORS_ORIGIN, API_CORS_ALLOW_METHODS
        mw = CORSMiddleware()
        assert mw is not None
        assert API_CORS_ORIGIN == "*"
