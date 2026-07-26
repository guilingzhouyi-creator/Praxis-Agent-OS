"""MessageGate 单测 — 规则匹配 / 依赖链 / 持久化 (S3/S5 修复点)。"""

from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from l3.message_gate import (
    MessageGateEngine,
    MessageGateRule,
    get_gate,
    reset_gate,
)
from l4.monitor_bus import MonitorEvent


def _make_engine(tmp_obj) -> MessageGateEngine:
    """Build an isolated engine pointing at a temp persist file.

    ``tmp_obj`` is either a ``TemporaryDirectory`` instance (use ``.name``)
    or a plain directory string.
    """
    base = getattr(tmp_obj, "name", tmp_obj)
    path = os.path.join(base, "gate.json")
    return MessageGateEngine(persist_path=path)


def _ev(type_: str = "network.peer.loss", severity: str = "crit",
        agent_id: str = "") -> MonitorEvent:
    return MonitorEvent(type=type_, source="t", severity=severity,
                        agent_id=agent_id)


class TestRuleMatching:
    """MessageGateRule.matches — pattern fields, type glob."""

    def test_empty_pattern_matches_anything(self):
        rule = MessageGateRule(id="r1", pattern={}, action="block")
        assert rule.matches(_ev(type_="anything"))

    def test_type_glob_match(self):
        rule = MessageGateRule(
            id="r1", pattern={"type": "network.*"}, action="block",
        )
        assert rule.matches(_ev(type_="network.peer.loss"))
        assert not rule.matches(_ev(type_="l1.kernel.interrupt"))

    def test_severity_exact_match(self):
        rule = MessageGateRule(
            id="r1", pattern={"severity": "crit"}, action="block",
        )
        assert rule.matches(_ev(severity="crit"))
        assert not rule.matches(_ev(severity="warn"))

    def test_agent_id_match(self):
        rule = MessageGateRule(
            id="r1", pattern={"agent_id": "writer-1"}, action="block",
        )
        assert rule.matches(_ev(agent_id="writer-1"))
        assert not rule.matches(_ev(agent_id="writer-2"))

    def test_multiple_pattern_fields_all_must_match(self):
        rule = MessageGateRule(
            id="r1",
            pattern={"type": "network.*", "severity": "crit"},
            action="block",
        )
        assert rule.matches(_ev(type_="network.peer.loss", severity="crit"))
        assert not rule.matches(_ev(type_="network.peer.loss", severity="warn"))


class TestEvaluate:
    """evaluate() priority ordering + triggered side-effect (S3 fix)."""

    def test_no_rules_returns_allow(self):
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            assert gate.evaluate(_ev()) == "allow"

    def test_block_rule_blocks_matching_event(self):
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            gate.add(MessageGateRule(
                id="block-net", pattern={"type": "network.*"},
                action="block", priority=5,
            ))
            assert gate.evaluate(_ev(type_="network.peer.loss")) == "block"

    def test_priority_highest_wins(self):
        """Higher priority rule wins over lower."""
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            gate.add(MessageGateRule(
                id="low-allow", pattern={"type": "network.*"},
                action="allow", priority=1,
            ))
            gate.add(MessageGateRule(
                id="high-block", pattern={"type": "network.*"},
                action="block", priority=10,
            ))
            assert gate.evaluate(_ev(type_="network.peer.loss")) == "block"

    def test_evaluate_records_triggered(self):
        """S3 fix: _triggered updated within single lock, then persisted."""
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            gate.add(MessageGateRule(
                id="r1", pattern={"type": "network.*"},
                action="block", priority=5,
            ))
            gate.evaluate(_ev(type_="network.peer.loss"))
            assert "r1" in gate._triggered


class TestDependencyChain:
    """depends_on gating + hold_timeout expiry."""

    def test_unmet_dependency_rule_skipped(self):
        """Rule B depends on Rule A; A not triggered → B not applied."""
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            gate.add(MessageGateRule(
                id="A", pattern={"type": "kernel.*"},
                action="block", priority=5,
            ))
            gate.add(MessageGateRule(
                id="B", pattern={"type": "network.*"},
                action="block", priority=10, depends_on=["A"],
            ))
            # Network event: B matches pattern but deps unmet → allow
            assert gate.evaluate(_ev(type_="network.peer.loss")) == "allow"

    def test_met_dependency_rule_applied(self):
        """Trigger A first, then B's dependency is satisfied."""
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            gate.add(MessageGateRule(
                id="A", pattern={"type": "kernel.*"},
                action="block", priority=5,
            ))
            gate.add(MessageGateRule(
                id="B", pattern={"type": "network.*"},
                action="block", priority=10, depends_on=["A"],
            ))
            # Trigger A
            gate.evaluate(_ev(type_="l1.kernel.interrupt"))
            assert "A" in gate._triggered
            # Now B's dependency is met
            assert gate.evaluate(_ev(type_="network.peer.loss")) == "block"

    def test_hold_timeout_expires_dependency(self):
        """After hold_timeout, triggered A no longer satisfies B's dep."""
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            gate.add(MessageGateRule(
                id="A", pattern={"type": "kernel.*"},
                action="block", priority=5, hold_timeout=0.01,
            ))
            gate.add(MessageGateRule(
                id="B", pattern={"type": "network.*"},
                action="block", priority=10, depends_on=["A"],
            ))
            gate.evaluate(_ev(type_="l1.kernel.interrupt"))
            time.sleep(0.05)  # exceed hold_timeout
            # A's triggered record is stale → B dep not met → allow
            assert gate.evaluate(_ev(type_="network.peer.loss")) == "allow"


class TestPersistence:
    """PersistableMixin round-trip via _persist/_restore."""

    def test_add_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gate.json")
            gate = MessageGateEngine(persist_path=path)
            gate.add(MessageGateRule(
                id="r1", pattern={"type": "network.*"},
                action="block", priority=5,
            ))
            assert os.path.exists(path)

    def test_restore_reloads_rules(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gate.json")
            gate1 = MessageGateEngine(persist_path=path)
            gate1.add(MessageGateRule(
                id="r1", pattern={"type": "network.*"},
                action="block", priority=5,
            ))

            gate2 = MessageGateEngine(persist_path=path)
            rules = gate2.list_rules()
            assert len(rules) == 1
            assert rules[0]["id"] == "r1"

    def test_remove_persists_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gate.json")
            gate1 = MessageGateEngine(persist_path=path)
            gate1.add(MessageGateRule(
                id="r1", pattern={"type": "network.*"},
                action="block", priority=5,
            ))
            gate1.remove("r1")

            gate2 = MessageGateEngine(persist_path=path)
            assert len(gate2.list_rules()) == 0


class TestToDict:
    """to_dict() public API — used by api_handlers_monitor (M6 fix)."""

    def test_to_dict_keys(self):
        with tempfile.TemporaryDirectory() as d:
            gate = _make_engine(d)
            gate.add(MessageGateRule(
                id="r1", pattern={"type": "network.*"},
                action="block", priority=5,
            ))
            d_out = gate.to_dict()
            assert "rules" in d_out
            assert "triggered_count" in d_out
            assert d_out["triggered_count"] == 0
            assert len(d_out["rules"]) == 1


class TestSingleton:
    """get_gate/reset_gate singleton accessors."""

    def test_get_gate_returns_same_instance(self):
        reset_gate()
        g1 = get_gate()
        g2 = get_gate()
        assert g1 is g2
        reset_gate()

    def test_reset_gate_clears_singleton(self):
        reset_gate()
        g1 = get_gate()
        reset_gate()
        g2 = get_gate()
        assert g1 is not g2
        reset_gate()
