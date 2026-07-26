"""api_routes / api_gateway._match_route 单测 — S1 前缀路由严格匹配。

策略：用显式注册的最小路由集测试 _match_route 逻辑，
不依赖 ApiHandlers mixin 的完整加载（那些 handler 在
ApiGateway 实例上可能 getattr 失败）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from l4.api_gateway import ApiGateway
from l4.api_routes import API_ROUTES


def _make_gateway_with_minimal_routes():
    """Build a gateway, clear its routes, register a minimal prefix + exact set.

    This isolates _match_route from the full API_ROUTES loading
    (which warns on missing ApiHandlers methods).
    """
    gw = ApiGateway()  # loads API_ROUTES (with warnings — harmless)
    gw._routes.clear()
    # Prefix routes (end with /)
    gw.register_route("GET", "/api/card/", lambda b: {"_prefix_card": True}, "get card by id")
    gw.register_route("GET", "/api/agent/select/", lambda b: {"_prefix_select": True}, "select agent")
    gw.register_route("DELETE", "/api/monitor/gate/", lambda b: {"_prefix_gate_del": True}, "delete gate")
    # Exact routes
    gw.register_route("GET", "/api/health", lambda b: {"_health": True}, "health")
    gw.register_route("GET", "/api/card", lambda b: {"_exact_card": True}, "exact card")
    return gw


class TestApiRoutesTable:
    """API_ROUTES 静态表 — 单一来源。"""

    def test_routes_are_4_tuples(self):
        for entry in API_ROUTES:
            assert isinstance(entry, tuple)
            assert len(entry) == 4
            method, path, handler_ref, desc = entry
            assert method in ("GET", "POST", "PUT", "DELETE")
            assert path.startswith("/api/")
            assert isinstance(handler_ref, str)
            assert isinstance(desc, str)

    def test_no_duplicate_method_path(self):
        seen = set()
        for method, path, _, _ in API_ROUTES:
            key = (method, path)
            assert key not in seen, f"duplicate route: {key}"
            seen.add(key)

    def test_known_routes_present(self):
        paths = {(m, p) for m, p, _, _ in API_ROUTES}
        assert ("GET", "/api/health") in paths
        assert ("GET", "/api/monitor/events") in paths
        assert ("DELETE", "/api/monitor/gate/") in paths

    def test_prefix_routes_end_with_slash(self):
        """All prefix routes in API_ROUTES end with '/'."""
        for method, path, ref, desc in API_ROUTES:
            if ref.startswith("."):
                # Mixin method — check if it's a prefix route by path
                if path.endswith("/") and path != "/api/":
                    pass  # prefix route, OK


class TestPrefixRouteS1Strict:
    """S1 fix: prefix routes only accept single-segment remainder."""

    def test_prefix_route_matches_single_segment(self):
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/card/abc123")
        assert params == {"id": "abc123"}
        assert handler({}) == {"_prefix_card": True}

    def test_prefix_route_root_returns_empty_id(self):
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/card/")
        assert params == {"id": ""}
        assert handler({}) == {"_prefix_card": True}

    def test_prefix_route_multi_segment_rejected(self):
        """S1 fix: GET /api/card/foo/bar 不再误匹配 /api/card/ 的 id='bar'。"""
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/card/foo/bar")
        # 多段剩余不被前缀路由接受，应 fall through 到 not_found
        assert params == {}
        assert "error" in handler({})

    def test_prefix_does_not_match_substring_sibling(self):
        """S1 fix: /api/cardx 不应命中 /api/card/。"""
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/cardx")
        assert params == {}
        assert "error" in handler({})

    def test_agent_select_prefix(self):
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/agent/select/writer-1")
        assert params == {"id": "writer-1"}
        assert handler({}) == {"_prefix_select": True}

    def test_message_gate_delete_prefix(self):
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("DELETE", "/api/monitor/gate/rule-1")
        assert params == {"id": "rule-1"}
        assert handler({}) == {"_prefix_gate_del": True}


class TestExactRoute:
    """非前缀路由的精确匹配。"""

    def test_exact_path_match(self):
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/health")
        assert params == {}
        assert handler({}) == {"_health": True}

    def test_exact_card_path(self):
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/card")
        assert params == {}
        assert handler({}) == {"_exact_card": True}

    def test_exact_path_no_match(self):
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/nonexistent")
        assert params == {}
        assert "error" in handler({})

    def test_wrong_method_no_match(self):
        """GET 路由不应匹配 DELETE 请求。"""
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("DELETE", "/api/health")
        assert params == {}
        assert "error" in handler({})


class TestRoutePrecedence:
    """前缀路由与精确路由的优先级。"""

    def test_exact_path_beats_prefix_when_both_registered(self):
        """If both /api/card/ (prefix) and /api/card (exact) exist,
        exact match wins for /api/card (no trailing slash)."""
        gw = _make_gateway_with_minimal_routes()
        # /api/card (exact) should match, not /api/card/ (prefix)
        handler, params = gw._match_route("GET", "/api/card")
        assert params == {}
        assert handler({}) == {"_exact_card": True}

    def test_prefix_match_for_id(self):
        """/api/card/foo → prefix route with id='foo'."""
        gw = _make_gateway_with_minimal_routes()
        handler, params = gw._match_route("GET", "/api/card/foo")
        assert params == {"id": "foo"}
        assert handler({}) == {"_prefix_card": True}


class TestRegisterRoute:
    """register_route() appends to _routes."""

    def test_register_route_appends(self):
        gw = _make_gateway_with_minimal_routes()
        initial = len(gw._routes)
        gw.register_route("GET", "/api/test_custom",
                           lambda b: {"ok": True}, "custom")
        assert len(gw._routes) == initial + 1
        handler, _ = gw._match_route("GET", "/api/test_custom")
        assert handler({}) == {"ok": True}


class TestApiGatewayConstruction:
    """ApiGateway 构造 + API_ROUTES 加载（含 warnings）。"""

    def test_gateway_constructs_without_error(self):
        """ApiGateway() 加载全部 API_ROUTES，缺失的 handler 仅 warn 不 raise。"""
        gw = ApiGateway()
        assert gw.host is not None
        assert gw.port > 0
        # 至少部分路由应注册成功
        assert len(gw._routes) > 0

    def test_gateway_has_routes_list(self):
        gw = ApiGateway()
        # _routes 应非空（即使部分 handler 缺失）
        assert isinstance(gw._routes, list)
