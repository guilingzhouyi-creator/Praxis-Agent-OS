"""Event chain tests — CARD_PENDING / APPROVAL_REQUIRED / APPROVAL_RESPONDED.

Verifies the frontend notification chain: pending enqueue and approval
gate hold/respond must emit the corresponding kernel signals so SSE/WS
clients receive them without polling.

Note: EventBus dispatches callbacks asynchronously (thread pool), so the
tests poll briefly for the expected event instead of asserting instantly.
"""

from __future__ import annotations

import time

import pytest


def _wait_for(captured: list[str], name: str, timeout: float = 1.0) -> bool:
    """Poll until the named event appears (async bus dispatch)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if name in captured:
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def seen_events():
    """Capture SignalType names emitted on the bus during a test."""
    from l1.kernel import get_event_bus

    bus = get_event_bus()
    captured: list[str] = []
    try:
        bus.on_any(lambda sig: captured.append(sig.type.name))
    except Exception:
        pass
    yield captured


class TestApprovalEvents:
    def test_request_emits_approval_required(self, seen_events):
        from l3.card.approval_gate import ApprovalGate, reset_gate

        reset_gate()
        gate = ApprovalGate()
        gate.request("write_file", "agent-a", {"path": "x"}, reason="needs eyes")
        assert _wait_for(seen_events, "APPROVAL_REQUIRED")

    def test_respond_emits_approval_responded(self, seen_events):
        from l3.card.approval_gate import ApprovalGate, reset_gate

        reset_gate()
        gate = ApprovalGate()
        req = gate.request("write_file", "agent-a", {"path": "x"})
        _wait_for(seen_events, "APPROVAL_REQUIRED")
        gate.respond(req.id, approved=True, response="ok")
        assert _wait_for(seen_events, "APPROVAL_RESPONDED")


class TestPendingEvents:
    def test_enqueue_emits_card_pending(self, seen_events):
        from l3.card.pending_queue import PendingQueue, reset_queue

        reset_queue()
        q = PendingQueue()
        q.enqueue("card-xyz", intent="deploy", domain="ops")
        assert _wait_for(seen_events, "CARD_PENDING")
