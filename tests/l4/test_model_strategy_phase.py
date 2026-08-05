"""Phase-strategy + clamp-warning + disabled-pack tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _setup():
    from l3.services.model_service import get_service as _gs
    _gs()._settings = None
    from l3.config.settings_center import get_center
    sc = get_center()
    sc.set("model_spec.strategies.deep.reasoning_effort", "high")
    sc.set("model_spec.strategies.deep.thinking_budget", 8192)
    sc.set("model_spec.strategies.deep.max_tokens", 8192)
    sc.set("model_spec.strategies.disabled.reasoning_effort", "high")
    sc.set("model_spec.strategies.disabled.enabled", False)
    for k in ("model_spec.l3a.max_tokens", "model_spec.l3a.temperature",
              "model_spec.l3a.reasoning_effort", "model_spec.l3a.thinking_budget",
              "model_spec.l3a.strategy", "think.max_reasoning", "think.max_budget"):
        sc.reset(k)
    return sc


class TestClampWarning:
    def test_clamp_logs_warning(self, caplog):
        from l3.services.model_service import get_service
        _setup()
        ms = get_service()
        sc = ms._settings_center()
        sc.set("think.max_reasoning", "medium")
        import logging
        with caplog.at_level(logging.WARNING, logger="l3.services.model_service"):
            ms.apply_strategy("l3a", "deep")
            d = ms.resolve_dict("l3a")
        assert d["reasoning_effort"] == "medium"
        assert any("clamped" in r.message for r in caplog.records)

    def test_budget_clamp(self, caplog):
        from l3.services.model_service import get_service
        _setup()
        ms = get_service()
        sc = ms._settings_center()
        sc.set("think.max_budget", 4096)
        import logging
        with caplog.at_level(logging.WARNING, logger="l3.services.model_service"):
            ms.apply_strategy("l3a", "deep")
            d = ms.resolve_dict("l3a")
        assert d["thinking_budget"] == 4096


class TestDisabledPack:
    def test_disabled_pack_rejected(self):
        from l3.services.model_service import get_service
        _setup()
        r = get_service().apply_strategy("l3a", "disabled")
        assert r["success"] is False
        assert "disabled" in r["error"]


class TestResolveStrategyPack:
    def test_pack_read(self):
        from l3.services.model_service import get_service
        _setup()
        d = get_service().resolve_strategy_pack("deep")
        assert d["reasoning_effort"] == "high"
        assert d["thinking_budget"] == 8192

    def test_unknown_pack_none(self):
        from l3.services.model_service import get_service
        _setup()
        assert get_service().resolve_strategy_pack("nope") is None


class TestPhaseStrategy:
    def test_card_phase_strategy_field(self):
        from l3.card.card_unified import CardUnified, PhaseMode
        card = CardUnified(nature="execution")
        phase = card.add_phase(name="plan", mode=PhaseMode.SINGLE,
                               strategy="deep")
        assert phase.strategy == "deep"
        d = card.to_dict()
        assert d["phases"][0]["strategy"] == "deep"

    def test_cardwrite_passes_strategy(self):
        from l3.cell.peers.l3a.helpers import cardwrite_handler
        r = cardwrite_handler({
            "nature": "execution",
            "title": "t",
            "phases": [{"name": "plan", "strategy": "deep",
                        "tasks": [{"action": "read_file", "target": "x.py"}]}],
        })
        assert r["success"] is True
        from l3.card.card_registry import get_registry
        with get_registry()._lock:
            card = get_registry()._cards.get(r["card_id"])
        assert card is not None
        assert card.phases[0].strategy == "deep"


class TestSubagentStrategy:
    def test_spec_strategy_field(self):
        from l3.agent.subagent_spec import SubAgentSpec
        spec = SubAgentSpec(name="x", description="d", strategy="balanced")
        d = spec.to_dict()
        assert d["strategy"] == "balanced"

    def test_resolve_applies_strategy(self):
        from l3.agent.subagent_spec import SubAgentSpec
        from l3.agent.subagent_task import SubAgentTask
        _setup()
        spec = SubAgentSpec(name="deep-runner", description="d",
                            model_spec="subagent", strategy="deep")
        task = SubAgentTask(task_id="t1", spec=spec, prompt="p")
        kwargs = task.resolve_model_kwargs()
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["thinking_budget"] == 8192


class TestScoutStrategy:
    def test_scout_session_accepts_strategy(self):
        from l3.agent.scout import ScoutSession
        s = ScoutSession("s1", "agent-a", "investigate", strategy="deep")
        assert s.strategy == "deep"

    def test_commission_default_no_strategy(self):
        from l3.agent.scout import ScoutPool
        pool = ScoutPool(min_idle=0, max_total=2)
        # no LLM is invoked without execute; just verify commission plumbing
        assert pool.max_total == 2


class TestL3ASubagentStrategy:
    def test_commission_strategy_plumbing(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool
        pool = L3ASubAgentPool(max_workers=1)
        try:
            r = pool.commission("card-planner", "plan x", strategy="deep")
            assert r["success"] is True
            assert r["task_id"]
            # spec default strategy applies when not overridden
            r2 = pool.commission("investigator", "look", strategy="")
            assert r2["success"] is True
        finally:
            pool.shutdown(wait=False)

    def test_resolve_model_config_with_strategy(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool
        _setup()
        cfg = L3ASubAgentPool._resolve_model_config("balanced")
        assert cfg["reasoning_effort"] == "low"
        cfg2 = L3ASubAgentPool._resolve_model_config()
        assert cfg2["reasoning_effort"] == "none"
