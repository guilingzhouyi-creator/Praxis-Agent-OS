"""API handlers for Card operations — extracted from api_handlers.py for modularity."""
from __future__ import annotations

from l1.kernel.params.agent import DEFAULT_CELL_ID
from l1.kernel.params.gatechain import GATECHAIN_LEDGER_LIMIT


def list_cards(body: dict) -> dict:
    """List registered cards, optionally filtered by state or approval status."""
    try:
        from l3.card.card_registry import get_registry
        state = body.get("state") or body.get("_id")
        approval_status = body.get("approval_status", "")
        cards = get_registry().list(state=state)
        if approval_status:
            cards = [c for c in cards if c.get("approval_status", "") == approval_status]
        return {"cards": cards, "count": len(cards)}
    except Exception as e:
        return {"cards": [], "count": 0, "error": str(e)}


def get_card(body: dict) -> dict:
    """Fetch a single card by id from the registry or event bus."""
    try:
        from l1.kernel import get_event_bus
        card_id = body.get("_id") or body.get("card_id", "")
        if not card_id:
            return {"success": False, "error": "card_id required"}
        from l3.card.card_registry import get_registry
        card = get_registry().get(card_id)
        if card:
            return {"success": True, "card": card}
        bus = get_event_bus()
        card = bus.query(lambda s: s.type.name == "task_assign" and s.data.get("card_id") == card_id)
        return {"card": card[0].data if card else None}
    except Exception as e:
        return {"error": str(e)}


def submit_card(body: dict) -> dict:
    """Submit a single card intent to the registry and return its id."""
    try:
        intent = body.get("intent") or body.get("_id", "")
        if not intent:
            return {"success": False, "error": "intent required"}
        domain = body.get("domain", ".")
        from l3.card.card_registry import get_registry
        cid = get_registry().submit(intent, domain)
        return {"success": True, "card_id": cid}
    except Exception as e:
        return {"success": False, "error": str(e)}


def submit_batch(body: dict) -> dict:
    """Submit a batch of card intents and return the submitted card ids."""
    try:
        cards = body.get("cards", [])
        if not cards:
            return {"success": False, "error": "batch empty"}
        from l3.card.card_registry import get_registry
        results = []
        for c in cards:
            cid = get_registry().submit(c.get("intent", ""), c.get("domain", "."))
            results.append(cid)
        return {"success": True, "submitted": len(results), "card_ids": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


def card_rollback(body: dict) -> dict:
    """Roll back the card with the given id on the default cell."""
    try:
        from l3.cell import get_cell
        card_id = body.get("card_id", "")
        cell = get_cell(DEFAULT_CELL_ID)
        return cell.rollback_card(card_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


def card_gate_history(body: dict) -> dict:
    """Return the gatechain ledger history for the given card id."""
    try:
        from l1.kernel.gatechain import get_gatechain
        card_id = body.get("card_id", "")
        gc = get_gatechain()
        return {"history": gc.ledger.recent(card_id, limit=GATECHAIN_LEDGER_LIMIT)}
    except Exception as e:
        return {"error": str(e)}


def sideload_dispatch(body: dict) -> dict:
    """Sideload-dispatch an intent directly on a cell outside the card pipeline."""
    try:
        intent = body.get("intent", "")
        domain = body.get("domain", ".")
        from l3.cell import get_cell
        cell = get_cell(DEFAULT_CELL_ID, [domain])
        result = cell.execute_card(intent, domain=domain)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
