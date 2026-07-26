"""ApiGateway tests — route registration, request dispatch, endpoint listing."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestApiGateway:
    def test_route_create(self):
        from l4.api_gateway import Route
        r = Route(method="GET", path="/api/health", handler=lambda: (200, {"ok": True}))
        assert r.method == "GET"
        assert r.path == "/api/health"

    def test_start_api(self):
        from l4.api_gateway import start_api, stop_api
        gw = start_api(port=18080, auth_token="test-token")
        assert gw is not None
        assert gw.port == 18080
        assert gw.auth_token == "test-token"
        stop_api()

    def test_endpoints_list(self):
        from l4.api_gateway import ApiGateway
        gw = ApiGateway(port=18081, auth_token="")
        eps = gw._endpoints()
        assert isinstance(eps, list)
        assert len(eps) > 0
        lines = " ".join(eps)
        assert "/api/health" in lines or "health" in lines

    def test_register_route(self):
        from l4.api_gateway import ApiGateway
        gw = ApiGateway(port=18082, auth_token="")
        gw.register_route("GET", "/api/v1/test", lambda b: {"ok": True}, "Test endpoint")
        result = gw._list_endpoints()
        assert result["endpoints"] is not None
        assert any("TEST" in e or "test" in e or "/api/v1/test" in e for e in result["endpoints"])

    def test_default_routes_populated(self):
        from l4.api_gateway import ApiGateway
        gw = ApiGateway(port=18083, auth_token="")
        assert len(gw._routes) >= 30  # all default routes

    def test_match_route_get(self):
        from l4.api_gateway import ApiGateway
        gw = ApiGateway(port=18084, auth_token="")
        handler, params = gw._match_route("GET", "/api/health")
        assert handler is not None
        result = handler({})
        assert isinstance(result, dict)

    def test_match_route_not_found(self):
        from l4.api_gateway import ApiGateway
        gw = ApiGateway(port=18085, auth_token="")
        handler, params = gw._match_route("GET", "/api/nonexistent")
        result = handler({})
        assert "error" in result or "not found" in str(result)

    def test_stop_api(self):
        from l4.api_gateway import start_api, stop_api
        start_api(port=18086, auth_token="")
        stop_api()
