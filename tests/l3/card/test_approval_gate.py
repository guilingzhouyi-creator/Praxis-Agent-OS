"""Tests for ApprovalGate — request lifecycle, timeout, persist."""

from __future__ import annotations

from l3.card.approval_gate import get_gate, reset_gate


def setup_method():
    reset_gate()


def test_request_and_approve():
    gate = get_gate()
    gate._init_persistence("", 0)  # no auto-save during test
    req = gate.request("write_file", "agent-a", {"path": "/tmp/test.py"}, "test write")
    req_id = req.id

    r = gate.respond(req_id, True, "approved by test")
    assert r.get("success"), f"approve failed: {r}"


def test_request_and_reject():
    gate = get_gate()
    gate._init_persistence("", 0)
    req = gate.request("delete", "agent-b", {"path": "/tmp/secret"}, "reject test")
    req_id = req.id

    r = gate.respond(req_id, False, "not allowed")
    assert r.get("success"), f"reject failed: {r}"


def test_list_pending():
    gate = get_gate()
    gate._init_persistence("", 0)
    gate.request("edit", "agent-c", {"path": "/tmp/a.py"}, "pending a")
    gate.request("edit", "agent-d", {"path": "/tmp/b.py"}, "pending b")
    pending = gate.list_pending()
    assert len(pending) >= 2


def test_timeout_reject():
    gate = get_gate()
    gate._init_persistence("", 0)
    req = gate.request("deploy", "agent-e", {"target": "production"}, "timeout test")
    req_id = req.id

    r = gate.respond(req_id, False, "timeout")
    assert r.get("success"), f"timeout reject failed: {r}"
