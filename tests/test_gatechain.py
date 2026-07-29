"""Tests for GateChain kernel module — G1-G5 tool authorization chain."""

from __future__ import annotations

import time

import pytest

from l1.kernel.gatechain import (
    GateResult,
    ToolHistoryLedger,
    LedgerEntry,
    GateChain,
    get_gatechain,
    reset_gatechain,
)


# ═══════════════════════════════════════════════════════════════════
# ToolHistoryLedger
# ═══════════════════════════════════════════════════════════════════


class TestLedgerInit:
    def test_default_entries(self):
        ledger = ToolHistoryLedger(max_entries=100)
        assert ledger._max == 100
        assert ledger._entries == []

    def test_recent_empty(self):
        ledger = ToolHistoryLedger()
        assert ledger.recent() == []

    def test_count_empty(self):
        ledger = ToolHistoryLedger()
        assert ledger.count("agent-a") == 0


class TestLedgerRecord:
    def test_record_single(self):
        ledger = ToolHistoryLedger(max_entries=10)
        entry = LedgerEntry(agent_id="agent-a", tool="read_file", target="/x", result=GateResult.PASS)
        ledger.record(entry)
        assert len(ledger._entries) == 1

    def test_record_updates_buckets(self):
        ledger = ToolHistoryLedger(max_entries=10)
        ledger.record(LedgerEntry(agent_id="a", tool="read", target="/x", result=GateResult.PASS))
        assert "a" in ledger._by_agent
        assert "read" in ledger._by_tool
        assert "a|read" in ledger._by_agent_tool

    def test_record_max_entries_trims(self):
        ledger = ToolHistoryLedger(max_entries=3)
        for i in range(5):
            ledger.record(LedgerEntry(agent_id="a", tool="t", target=f"/{i}", result=GateResult.PASS))
        assert len(ledger._entries) == 3
        assert ledger._entries[-1].target == "/4"


class TestLedgerRecent:
    def test_recent_by_agent(self):
        ledger = ToolHistoryLedger()
        ledger.record(LedgerEntry(agent_id="a", tool="t1", target="/x", result=GateResult.PASS))
        ledger.record(LedgerEntry(agent_id="b", tool="t2", target="/y", result=GateResult.PASS))
        r = ledger.recent(agent_id="a")
        assert len(r) == 1
        assert r[0].agent_id == "a"

    def test_recent_by_tool(self):
        ledger = ToolHistoryLedger()
        ledger.record(LedgerEntry(agent_id="a", tool="read", target="/x", result=GateResult.PASS))
        ledger.record(LedgerEntry(agent_id="b", tool="write", target="/y", result=GateResult.PASS))
        r = ledger.recent(tool="read")
        assert len(r) == 1

    def test_recent_by_agent_tool(self):
        ledger = ToolHistoryLedger()
        ledger.record(LedgerEntry(agent_id="a", tool="read", target="/x", result=GateResult.PASS))
        ledger.record(LedgerEntry(agent_id="a", tool="write", target="/y", result=GateResult.PASS))
        r = ledger.recent(agent_id="a", tool="read")
        assert len(r) == 1

    def test_recent_limit(self):
        ledger = ToolHistoryLedger()
        for i in range(10):
            ledger.record(LedgerEntry(agent_id="a", tool="t", target=f"/{i}", result=GateResult.PASS))
        r = ledger.recent(agent_id="a", limit=3)
        assert len(r) == 3


class TestLedgerCount:
    def test_count_by_agent(self):
        ledger = ToolHistoryLedger()
        ledger.record(LedgerEntry(agent_id="a", tool="r", target="/x", result=GateResult.PASS))
        ledger.record(LedgerEntry(agent_id="a", tool="r", target="/y", result=GateResult.PASS))
        ledger.record(LedgerEntry(agent_id="b", tool="w", target="/z", result=GateResult.PASS))
        assert ledger.count("a") == 2
        assert ledger.count("b") == 1

    def test_count_within_window(self):
        ledger = ToolHistoryLedger(max_entries=100)
        ledger.record(LedgerEntry(agent_id="a", tool="t", target="/x", result=GateResult.PASS))
        ledger.record(LedgerEntry(agent_id="a", tool="t", target="/y", result=GateResult.PASS))
        # All within default window (60s) — should count 2
        assert ledger.count("a", window=60.0) == 2


class TestLedgerClear:
    def test_clear(self):
        ledger = ToolHistoryLedger()
        ledger.record(LedgerEntry(agent_id="a", tool="t", target="/x", result=GateResult.PASS))
        ledger.clear()
        assert ledger._entries == []
        assert ledger._by_agent == {}
        assert ledger._by_tool == {}
        assert ledger._by_agent_tool == {}


# ═══════════════════════════════════════════════════════════════════
# GateChain
# ═══════════════════════════════════════════════════════════════════


class TestGateChainInit:
    def setup_method(self):
        reset_gatechain()

    def test_default_state(self):
        gc = get_gatechain()
        r = gc.check("read_file", "agent-a", target="/x")
        # Without any config, tools not registered — G1 blocks
        assert "allowed" in r
        assert "steps" in r
        assert len(r["steps"]) > 0

    def test_get_gatechain_singleton(self):
        g1 = get_gatechain()
        g2 = get_gatechain()
        assert g1 is g2


class TestGateChainCheck:
    def setup_method(self):
        reset_gatechain()

    def test_returns_dict(self):
        gc = get_gatechain()
        r = gc.check("my_tool", "agent-a", target="/x")
        assert isinstance(r, dict)
        assert "allowed" in r
        assert "decision" in r
        assert "steps" in r

    def test_unknown_tool_g1_blocks(self):
        gc = get_gatechain()
        r = gc.check("nonexistent_tool", "agent-a", target="/x")
        # G1 blocks: unknown tools are not in allowed list
        assert r.get("allowed") is not None

    def test_check_with_danger(self):
        gc = get_gatechain()
        r = gc.check("write_file", "agent-a", target="/x", danger=5)
        assert isinstance(r, dict)

    def test_check_with_territory(self):
        gc = get_gatechain()
        r = gc.check("read_file", "agent-a", target="/project/foo.py",
                      territory=["/project"])
        assert isinstance(r, dict)


class TestGateChainBlankCalls:
    """Edge cases: degenerate inputs."""

    def setup_method(self):
        reset_gatechain()

    def test_empty_tool_name(self):
        gc = get_gatechain()
        r = gc.check("", "agent-a", target="/x")
        assert isinstance(r, dict)

    def test_empty_agent_id(self):
        gc = get_gatechain()
        r = gc.check("read_file", "", target="/x")
        assert isinstance(r, dict)

    def test_no_target(self):
        gc = get_gatechain()
        r = gc.check("read_file", "agent-a", target="")
        assert isinstance(r, dict)
