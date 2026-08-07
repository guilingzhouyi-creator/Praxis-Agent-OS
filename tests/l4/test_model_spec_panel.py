"""Model-spec panel API + L2 shell command tests (overview/caps/spec)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _setup():
    from l3.services.model_service import get_service as _gs

    _gs()._settings = None
    from l3.config.settings_center import get_center

    sc = get_center()
    sc.set("model_spec.strategies.fast.reasoning_effort", "none")
    sc.set("model_spec.strategies.deep.reasoning_effort", "high")
    sc.set("model_spec.strategies.deep.thinking_budget", 8192)
    for k in (
        "model_spec.l3a.max_tokens",
        "model_spec.l3a.temperature",
        "model_spec.l3a.reasoning_effort",
        "model_spec.l3a.thinking_budget",
        "model_spec.l3a.strategy",
        "think.max_reasoning",
        "think.max_budget",
    ):
        sc.reset(k)
    return sc


class TestOverviewApi:
    def test_overview_full_panel(self):
        from l4.api_handlers.api_handlers_providers import handle_model_spec_overview

        _setup()
        r = handle_model_spec_overview({})
        assert r["success"] is True
        assert set(r["specs"].keys()) == {"scout", "l3a", "l3a_subagent", "subagent", "r4_agent"}
        assert "reasoning_effort" in r["specs"]["l3a"]["current"]
        assert r["caps"]["max_reasoning"] == "max"
        assert "fast" in r["strategies"]
        assert r["strategies"]["deep"]["reasoning_effort"] == "high"
        assert "none" in r["tiers"] and "max" in r["tiers"]

    def test_overview_reflects_applied_strategy(self):
        from l3.services.model_service import get_service
        from l4.api_handlers.api_handlers_providers import handle_model_spec_overview

        _setup()
        get_service().apply_strategy("l3a", "deep")
        r = handle_model_spec_overview({})
        assert r["specs"]["l3a"]["strategy"] == "deep"
        assert r["specs"]["l3a"]["current"]["reasoning_effort"] == "high"


class TestCapsApi:
    def test_get_caps(self):
        from l4.api_handlers.api_handlers_providers import handle_think_caps_get

        _setup()
        r = handle_think_caps_get({})
        assert r["caps"]["max_reasoning"] == "max"

    def test_set_caps(self):
        from l3.config.settings_center import get_center
        from l3.services.model_service import get_service
        from l4.api_handlers.api_handlers_providers import handle_think_caps_set

        _setup()
        try:
            r = handle_think_caps_set({"max_reasoning": "high", "max_budget": 8192})
            assert r["success"] is True
            assert r["caps"] == {"max_reasoning": "high", "max_budget": 8192}
            # clamping is enforced through resolve
            get_service().apply_strategy("l3a", "deep")
            d = get_service().resolve_dict("l3a")
            assert d["reasoning_effort"] == "high"
            assert d["thinking_budget"] == 8192
        finally:
            get_center().reset("think.max_reasoning")
            get_center().reset("think.max_budget")
            get_center().reset("model_spec.l3a.max_tokens")
            get_center().reset("model_spec.l3a.reasoning_effort")
            get_center().reset("model_spec.l3a.thinking_budget")
            get_center().reset("model_spec.l3a.strategy")

    def test_set_invalid_tier_rejected(self):
        from l4.api_handlers.api_handlers_providers import handle_think_caps_set

        _setup()
        r = handle_think_caps_set({"max_reasoning": "ultra"})
        assert r["success"] is False

    def test_set_negative_budget_rejected(self):
        from l4.api_handlers.api_handlers_providers import handle_think_caps_set

        _setup()
        r = handle_think_caps_set({"max_budget": -5})
        assert r["success"] is False


class TestShellCommand:
    def test_shell_spec_overview(self):
        from l2.l2_shell.commands.model import _cmd_model_spec

        _setup()
        r = _cmd_model_spec([])
        assert r["success"] is True
        assert "specs" in r

    def test_shell_strategy_apply_and_clear(self):
        from l2.l2_shell.commands.model import _cmd_model_spec

        _setup()
        r = _cmd_model_spec(["strategy", "l3a", "fast"])
        assert r["success"] is True
        r2 = _cmd_model_spec(["clear", "l3a"])
        assert r2["success"] is True
        assert "restored" in r2

    def test_shell_caps(self):
        from l2.l2_shell.commands.model import _cmd_model_spec
        from l3.config.settings_center import get_center

        _setup()
        try:
            r = _cmd_model_spec(["caps", "medium"])
            assert r["success"] is True
            assert r["caps"]["max_reasoning"] == "medium"
        finally:
            get_center().reset("think.max_reasoning")
            get_center().reset("think.max_budget")

    def test_shell_bad_subcommand(self):
        from l2.l2_shell.commands.model import _cmd_model_spec

        r = _cmd_model_spec(["bogus"])
        assert r["success"] is False

    def test_routes_registered(self):
        from l4.api.api_routes import API_ROUTES

        paths = {p for _, p, _, _ in API_ROUTES}
        assert "/api/v2/model-spec/overview" in paths
        assert "/api/v2/model-spec/caps" in paths
