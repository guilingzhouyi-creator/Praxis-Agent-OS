"""Peer-agent think strategy tests (think scopes: global/cell/agent)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _setup():
    from l3.services.model_service import get_service as _gs

    _gs()._settings = None
    from l3.scheduler.think_registry import get_think_registry, reset_think_registry

    reset_think_registry()
    from l3.config.settings_center import get_center

    sc = get_center()
    sc.set("model_spec.strategies.fast.reasoning_effort", "none")
    sc.set("model_spec.strategies.deep.reasoning_effort", "high")
    sc.set("model_spec.strategies.deep.thinking_budget", 8192)
    sc.set("model_spec.strategies.disabled.reasoning_effort", "high")
    sc.set("model_spec.strategies.disabled.enabled", False)
    return get_think_registry()


class TestRegistryStrategies:
    def test_global_apply_and_resolve(self):
        reg = _setup()
        r = reg.apply_strategy("global", "", "deep")
        assert r["success"] is True
        cfg = reg.resolve("cell-1", "agent-a")
        assert cfg["reasoning_effort"] == "high"
        assert cfg["thinking_budget"] == 8192

    def test_cell_apply_overrides_global(self):
        reg = _setup()
        reg.apply_strategy("global", "", "deep")
        reg.apply_strategy("cell", "cell-1", "fast")
        cfg = reg.resolve("cell-1", "agent-a")
        assert cfg["reasoning_effort"] == "none"  # cell wins over global

    def test_agent_apply_highest_priority(self):
        reg = _setup()
        reg.apply_strategy("cell", "cell-1", "fast")
        r = reg.apply_strategy("agent", "cell-1.agent-b", "deep")
        assert r["success"] is True
        cfg = reg.resolve("cell-1", "agent-b")
        assert cfg["reasoning_effort"] == "high"

    def test_clear_agent_restores(self):
        reg = _setup()
        reg.apply_strategy("agent", "cell-1.agent-b", "deep")
        reg.clear_strategy("agent", "cell-1.agent-b")
        cfg = reg.resolve("cell-1", "agent-b")
        assert cfg.get("reasoning_effort", "none") != "high"

    def test_unknown_strategy_rejected(self):
        reg = _setup()
        r = reg.apply_strategy("global", "", "nope")
        assert r["success"] is False

    def test_disabled_strategy_rejected(self):
        reg = _setup()
        r = reg.apply_strategy("global", "", "disabled")
        assert r["success"] is False

    def test_unknown_scope_rejected(self):
        reg = _setup()
        r = reg.apply_strategy("bogus", "", "deep")
        assert r["success"] is False

    def test_auto_balance_still_works(self):
        reg = _setup()
        reg.set_cell("cell-1", thinking_budget=8192, distribution="auto_balance")
        cfg = reg.resolve("cell-1", "agent-a", active_agents=4)
        assert cfg["thinking_budget"] == 8192 // 4


class TestPeerApi:
    def test_apply_via_api(self):
        from l4.api_handlers.api_handlers_providers import handle_peer_strategy_apply

        reg = _setup()
        r = handle_peer_strategy_apply({"scope": "agent", "name": "cell-1.agent-a", "strategy": "deep"})
        assert r["success"] is True
        cfg = reg.resolve("cell-1", "agent-a")
        assert cfg["reasoning_effort"] == "high"

    def test_clear_via_api(self):
        from l4.api_handlers.api_handlers_providers import (
            handle_peer_strategy_apply,
            handle_peer_strategy_clear,
        )

        reg = _setup()
        handle_peer_strategy_apply({"scope": "global", "strategy": "deep"})
        r = handle_peer_strategy_clear({"scope": "global"})
        assert r["success"] is True
        assert reg.resolve("cell-1", "agent-a")["reasoning_effort"] == "none"

    def test_get_via_api(self):
        from l4.api_handlers.api_handlers_providers import handle_peer_strategy_get

        _setup()
        r = handle_peer_strategy_get({})
        assert r["success"] is True
        assert "global" in r["state"]

    def test_requires_scope(self):
        from l4.api_handlers.api_handlers_providers import handle_peer_strategy_apply

        r = handle_peer_strategy_apply({"strategy": "deep"})
        assert r["success"] is False


class TestOverviewPeers:
    def test_overview_includes_peers(self):
        from l4.api_handlers.api_handlers_providers import handle_model_spec_overview

        _setup()
        r = handle_model_spec_overview({})
        assert "peers" in r
        assert "global" in r["peers"]


class TestShellPeer:
    def test_shell_peer_apply(self):
        from l2.l2_shell.commands.model import _cmd_model_spec

        reg = _setup()
        r = _cmd_model_spec(["peer", "agent", "cell-1.agent-a", "deep"])
        assert r["success"] is True
        assert reg.resolve("cell-1", "agent-a")["reasoning_effort"] == "high"

    def test_shell_peer_clear(self):
        from l2.l2_shell.commands.model import _cmd_model_spec

        reg = _setup()
        _cmd_model_spec(["peer", "agent", "cell-1.agent-a", "deep"])
        r = _cmd_model_spec(["peer", "clear", "agent", "cell-1.agent-a"])
        assert r["success"] is True
        assert reg.resolve("cell-1", "agent-a")["reasoning_effort"] == "none"

    def test_shell_peer_bad(self):
        from l2.l2_shell.commands.model import _cmd_model_spec

        r = _cmd_model_spec(["peer", "bogus"])
        assert r["success"] is False
