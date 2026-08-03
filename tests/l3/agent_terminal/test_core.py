"""Tests for AgentTerminal — lifecycle, card dispatch, worker loop, async scout."""

from __future__ import annotations

from l3.agent_terminal import AgentTerminal


def test_create_agent_terminal():
    t = AgentTerminal("test-agent", role="writer", territory=["src"], cell_id="cell-1")
    assert t.agent_id == "test-agent"
    assert t.role == "writer"
    assert t.territory == ["src"]
    assert t.cell_id == "cell-1"
    assert t.status.name == "BOOTING"


def test_terminal_boot_and_shutdown():
    t = AgentTerminal("boot-agent", role="reader", territory=["."])
    r = t.boot()
    assert r.get("success"), f"boot failed: {r}"
    assert t.status.name == "IDLE"
    r = t.shutdown()
    assert r.get("success")
    assert t.status.name == "STOPPED"


def test_status_report():
    t = AgentTerminal("status-agent", role="scout")
    r = t.status_report()
    assert r["agent_id"] == "status-agent"
    assert r["role"] == "scout"
    assert r["status"] == "BOOTING"
    assert r["alive"] is False
    assert r["paused"] is False


def test_session_reachable_after_boot():
    t = AgentTerminal("reach-agent")
    assert t.session_reachable().get("reachable") is False
    t.boot()
    try:
        r = t.session_reachable()
        assert r.get("reachable"), f"should be reachable: {r}"
    finally:
        t.shutdown()


def test_pause_resume():
    t = AgentTerminal("pause-agent")
    t.boot()
    try:
        r = t.pause()
        assert r.get("paused")
        assert t.status.name == "BLOCKED"
        r = t.resume()
        assert r.get("resumed")
        assert t.status.name == "IDLE"
    finally:
        t.shutdown()
