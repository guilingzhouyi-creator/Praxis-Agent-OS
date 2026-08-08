"""API handler mixin — approvals, pending queue and card-gate handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations

from l1.kernel.params.agent import DEFAULT_CELL_ID


def list_approvals(body: dict | None = None) -> dict:
    """List pending approvals from the approval gate."""
    try:
        from l3.card.approval_gate import get_gate

        return {"pending": get_gate().list_pending()}
    except Exception as e:
        return {"error": str(e)}


def approval_respond(body: dict) -> dict:
    """Respond to a pending approval request."""
    try:
        from l3.card.approval_gate import get_gate

        req_id = body.get("id", "")
        approved = body.get("approved", False)
        response = body.get("response", "")
        return get_gate().respond(req_id, approved, response)
    except Exception as e:
        return {"error": str(e)}


def card_gate_config(body: dict | None = None) -> dict:
    """Card-gate statistics."""
    try:
        from l3.card.card_gate import stats as _gate_stats

        return _gate_stats()
    except Exception as e:
        return {"error": str(e)}


def card_gate_config_set(body: dict) -> dict:
    """Apply card-gate configuration."""
    try:
        from l3.card.card_gate import get_gate

        gate = get_gate()
        gate.load_config(body)
        return {"success": True, "applied": list(body.keys())}
    except Exception as e:
        return {"error": str(e)}


def card_gate_history(body: dict | None = None) -> dict:
    """Card-gate decision history."""
    try:
        from l3.card.card_gate import list_history

        limit = int((body or {}).get("limit", 50))
        return {"history": list_history(limit), "count": limit}
    except Exception as e:
        return {"error": str(e)}


def pending_list(body: dict | None = None) -> dict:
    """List pending-queue entries by status."""
    try:
        from l3.card.pending_queue import get_queue

        status = (body or {}).get("status", "PENDING")
        limit = int((body or {}).get("limit", 50))
        return {"pending": get_queue().list(status=status, limit=limit)}
    except Exception as e:
        return {"error": str(e)}


def pending_approve(body: dict) -> dict:
    """Approve a pending-queue entry."""
    try:
        from l3.card.pending_queue import get_queue

        mid = body.get("id", "")
        if not mid:
            return {"error": "id is required"}
        return get_queue().approve(mid, body.get("response", ""))
    except Exception as e:
        return {"error": str(e)}


def pending_reject(body: dict) -> dict:
    """Reject a pending-queue entry."""
    try:
        from l3.card.pending_queue import get_queue

        mid = body.get("id", "")
        if not mid:
            return {"error": "id is required"}
        return get_queue().reject(mid, body.get("response", ""))
    except Exception as e:
        return {"error": str(e)}


def pending_escalate(body: dict) -> dict:
    """Escalate a pending-queue entry."""
    try:
        from l3.card.pending_queue import get_queue

        mid = body.get("id", "")
        if not mid:
            return {"error": "id is required"}
        return get_queue().escalate(mid)
    except Exception as e:
        return {"error": str(e)}


def pending_priority(body: dict) -> dict:
    """Set priority on a pending-queue entry."""
    try:
        from l3.card.pending_queue import get_queue

        mid = body.get("id", "")
        priority = int(body.get("priority", 5))
        if not mid:
            return {"error": "id is required"}
        return get_queue().set_priority(mid, priority)
    except Exception as e:
        return {"error": str(e)}


def pending_stats(body: dict | None = None) -> dict:
    """Pending-queue statistics."""
    try:
        from l3.card.pending_queue import get_queue

        return get_queue().stats()
    except Exception as e:
        return {"error": str(e)}


def card_gate_stats(body: dict | None = None) -> dict:
    """Card-gate statistics (alias of card_gate_config)."""
    try:
        from l3.card.card_gate import stats as _gate_stats

        return _gate_stats()
    except Exception as e:
        return {"error": str(e)}


def card_approval_trail(body: dict) -> dict:
    """Approval trail for a card."""
    try:
        from l3.card.card_registry import get_registry

        card_id = body.get("_id", "")
        card = get_registry().get(card_id)
        if not card:
            return {"error": f"card not found: {card_id}"}
        return {
            "card_id": card_id,
            "approval": {
                "status": card.approval_status,
                "size": card.approval_size,
                "at": card.approval_at,
                "by": card.approval_by,
            },
        }
    except Exception as e:
        return {"error": str(e)}


def gate_pending(body: dict | None = None) -> dict:
    """List pending card-gate entries."""
    try:
        from l3.card.card_gate import list_pending

        pending = list_pending()
        return {"pending": pending, "count": len(pending)}
    except Exception as e:
        return {"error": str(e)}


def gate_respond(body: dict) -> dict:
    """Respond to a card-gate approval."""
    try:
        from l3.card.card_gate import approve

        card_id = body.get("card_id", "")
        if not card_id:
            return {"error": "card_id is required"}
        decision = bool(body.get("approve", True))
        response = body.get("response", "")
        return approve(card_id, decision, response)
    except Exception as e:
        return {"error": str(e)}


def rollback_cell_context(body: dict | None = None) -> dict:
    """Cell rollback ring + card snapshot summary (moved from api_handlers_cells)."""
    try:
        from l3.cell import get_cell

        cell_id = (body or {}).get("cell_id", DEFAULT_CELL_ID)
        cell = get_cell(cell_id)
        ring = cell._rollback_ring
        return {
            "ring_size": len(ring),
            "max_size": 20,
            "recent": ring.all()[-5:] if ring.all() else [],
            "snapshot_count": len(cell._card_snapshots),
        }
    except Exception as e:
        return {"error": str(e)}
