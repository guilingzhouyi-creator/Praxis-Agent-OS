"""API gateway — route registration, start/stop."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestApiGateway:
    def test_route_dataclass(self):
        from l4.api.api_gateway import Route
        route = Route(method="GET", path="/api/test", handler=lambda r: {"ok": True})
        assert route.method == "GET"
        assert route.path == "/api/test"
        assert callable(route.handler)

    def test_create_gateway(self):
        from l4.api.api_gateway import ApiGateway, stop_api
        stop_api()
        gw = ApiGateway(host="127.0.0.1", port=0)
        assert gw is not None
        assert gw.host == "127.0.0.1"
        assert gw.port == 0
        gw.stop()

    def test_register_route(self):
        from l4.api.api_gateway import ApiGateway, stop_api
        stop_api()
        gw = ApiGateway(host="127.0.0.1", port=0)
        gw.register_route("GET", "/api/test", handler=lambda r: {"ok": True})
        assert len(gw._routes) >= 1
        gw.stop()
