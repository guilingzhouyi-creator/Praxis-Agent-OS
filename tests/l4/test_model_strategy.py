"""Model strategy pack switching tests — apply/clear/get + batch + resolve effect."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _setup_strategies():
    """Seed strategy definitions + a clean spec state."""
    from l3.services.model_service import get_service as _gs
    _gs()._settings = None  # rebind to the fresh center (conftest resets singletons)
    from l3.config.settings_center import get_center
    sc = get_center()
    sc.set("model_spec.strategies.fast.max_tokens", 2048)
    sc.set("model_spec.strategies.fast.reasoning_effort", "none")
    sc.set("model_spec.strategies.deep.max_tokens", 8192)
    sc.set("model_spec.strategies.deep.reasoning_effort", "high")
    sc.set("model_spec.strategies.deep.thinking_budget", 8192)
    sc.reset("model_spec.l3a.max_tokens")
    sc.reset("model_spec.l3a.temperature")
    sc.reset("model_spec.l3a.reasoning_effort")
    sc.reset("model_spec.l3a.thinking_budget")
    sc.reset("model_spec.l3a.strategy")


class TestStrategyApply:
    def test_apply_changes_resolution(self):
        from l3.services.model_service import get_service
        _setup_strategies()
        ms = get_service()
        r = ms.apply_strategy("l3a", "deep")
        assert r["success"] is True
        assert r["strategy"] == "deep"
        d = ms.resolve_dict("l3a")
        assert d["max_tokens"] == 8192
        assert d["reasoning_effort"] == "high"
        assert d["thinking_budget"] == 8192

    def test_unknown_strategy_fails(self):
        from l3.services.model_service import get_service
        _setup_strategies()
        r = get_service().apply_strategy("l3a", "nope")
        assert r["success"] is False

    def test_current_strategy_reports(self):
        from l3.services.model_service import get_service
        _setup_strategies()
        ms = get_service()
        assert ms.current_strategy("l3a")["strategy"] == "defaults"
        ms.apply_strategy("l3a", "fast")
        cur = ms.current_strategy("l3a")
        assert cur["strategy"] == "fast"
        assert cur["overrides"]["reasoning_effort"] == "none"

    def test_clear_restores_defaults(self):
        from l3.services.model_service import get_service
        _setup_strategies()
        ms = get_service()
        ms.apply_strategy("l3a", "deep")
        r = ms.clear_strategy("l3a")
        assert r["success"] is True
        d = ms.resolve_dict("l3a")
        assert d["max_tokens"] == 4096  # L1 default
        assert ms.current_strategy("l3a")["strategy"] == "defaults"


class TestStrategyApi:
    def test_handlers_exist(self):
        from l4.api_handlers.api_handlers_providers import (
            handle_model_strategy_apply,
            handle_model_strategy_apply_many,
            handle_model_strategy_clear,
            handle_model_strategy_get,
        )
        assert callable(handle_model_strategy_apply)
        assert callable(handle_model_strategy_apply_many)
        assert callable(handle_model_strategy_clear)
        assert callable(handle_model_strategy_get)

    def test_apply_via_api(self):
        from l3.services.model_service import get_service
        from l4.api_handlers.api_handlers_providers import (
            handle_model_strategy_apply,
            handle_model_strategy_get,
        )
        _setup_strategies()
        r = handle_model_strategy_apply("l3a", {"strategy": "deep"})
        assert r["success"] is True
        assert get_service().resolve_dict("l3a")["reasoning_effort"] == "high"
        g = handle_model_strategy_get("l3a", {})
        assert g["strategy"] == "deep"

    def test_clear_via_api(self):
        from l3.services.model_service import get_service
        from l4.api_handlers.api_handlers_providers import (
            handle_model_strategy_apply,
            handle_model_strategy_clear,
        )
        _setup_strategies()
        handle_model_strategy_apply("l3a", {"strategy": "deep"})
        r = handle_model_strategy_clear("l3a", {})
        assert r["success"] is True
        assert get_service().resolve_dict("l3a")["max_tokens"] == 4096

    def test_batch_apply_all(self):
        from l3.services.model_service import get_service
        from l4.api_handlers.api_handlers_providers import handle_model_strategy_apply_many
        _setup_strategies()
        r = handle_model_strategy_apply_many({"strategy": "fast", "specs": ["all"]})
        assert r["success"] is True
        assert len(r["specs"]) == 5
        for name in ["scout", "l3a", "l3a_subagent", "subagent", "r4_agent"]:
            assert get_service().resolve_dict(name)["reasoning_effort"] == "none"

    def test_batch_requires_args(self):
        from l4.api_handlers.api_handlers_providers import handle_model_strategy_apply_many
        assert handle_model_strategy_apply_many({})["success"] is False
        assert handle_model_strategy_apply_many({"strategy": "fast"})["success"] is False

    def test_apply_requires_name(self):
        from l4.api_handlers.api_handlers_providers import handle_model_strategy_apply
        r = handle_model_strategy_apply("", {"strategy": "deep"})
        assert r["success"] is False


class TestRoutes:
    def test_routes_registered(self):
        from l4.api.api_routes import API_ROUTES
        paths = {p for _, p, _, _ in API_ROUTES}
        assert "/api/v2/model-spec/{name}/strategy" in paths
        assert "/api/v2/model-spec/strategy/apply" in paths


class TestEffortTiers:
    def test_xhigh_max_constants(self):
        from l1.kernel.params.api import (
            REASONING_EFFORT_HIGH,
            REASONING_EFFORT_MAX,
            REASONING_EFFORT_XHIGH,
            THINK_MAX_REASONING,
        )
        assert REASONING_EFFORT_XHIGH == "xhigh"
        assert REASONING_EFFORT_MAX == "max"
        assert THINK_MAX_REASONING == REASONING_EFFORT_MAX

    def test_clamp_to_xhigh_ceiling(self):
        from l3.services.model_service import get_service
        _setup_strategies()
        ms = get_service()
        sc = ms._settings_center()
        sc.set("model_spec.strategies.xhigh.reasoning_effort", "xhigh")
        sc.set("think.max_reasoning", "xhigh")
        ms.apply_strategy("l3a", "xhigh")
        d = ms.resolve_dict("l3a")
        assert d["reasoning_effort"] == "xhigh"
        sc.set("think.max_reasoning", "high")
        d2 = ms.resolve_dict("l3a")
        assert d2["reasoning_effort"] == "high"  # clamped down
        sc.reset("think.max_reasoning")
        sc.reset("model_spec.l3a.max_tokens")
        sc.reset("model_spec.l3a.reasoning_effort")
        sc.reset("model_spec.l3a.thinking_budget")
        sc.reset("model_spec.l3a.strategy")
