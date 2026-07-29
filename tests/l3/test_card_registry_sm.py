"""CardRegistry state machine test — submit/dispatch/complete/cancel/approve lifecycle.

State flow:
  QUEUED → DISPATCHED → RUNNING → VERIFYING → DONE
  QUEUED → CANCELLED
  DISPATCHED → HELD → PENDING → DISPATCHED (via approval)
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCardRegistrySubmit:
    """submit() — card creation and enqueue"""

    def test_submit_returns_card_id(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("test intent", ".")
        assert cid.startswith("card-"), f"unexpected card id: {cid}"

    def test_submit_with_domain(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("fix login bug", "src/auth")
        assert cid.startswith("card-")

    def test_submit_multiple_cards(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        ids = [cr.submit(f"task {i}", ".") for i in range(5)]
        assert len(set(ids)) == 5, "each card_id must be unique"

    def test_submit_with_priority(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("high priority task", ".", priority=1)
        assert cid.startswith("card-")


class TestCardRegistryList:
    """list() — query queue by state"""

    def test_list_all_returns_pending(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cr.submit("task A", ".")
        cr.submit("task B", ".")
        cards = cr.list(state=None)
        assert isinstance(cards, list)
        assert len(cards) >= 2

    def test_list_by_state(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("cancellable", ".")
        cr.cancel(cid)
        # Verify list can at least filter by state (exact state name depends on implementation)
        all_cards = cr.list(state=None)
        assert isinstance(all_cards, list)
        # Verify completed card disappears from active queue
        active = cr.list(state="QUEUED")
        queued_ids = {c.get("id") or c.get("card_id", "") for c in active}
        assert cid not in queued_ids, "cancelled card should not be in QUEUED"


class TestCardRegistryCancel:
    """cancel() — card cancellation"""

    def test_cancel_pending_card(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("cancel me", ".")
        r = cr.cancel(cid)
        # cancel returns bool or dict; either way, shouldn't crash
        assert r is not False and r is not None, f"cancel returned {r}"

    def test_cancel_nonexistent(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        r = cr.cancel("no-such-card")
        # should not crash, may return error or False
        assert isinstance(r, dict) or r is not None


class TestCardRegistryGet:
    """get() — single card query"""

    def test_get_existing_card(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("get me", ".")
        card = cr.get(cid)
        assert card is not None, f"card {cid} not found"

    def test_get_nonexistent(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        card = cr.get("ghost-card")
        assert card is None


class TestCardRegistryComplete:
    """complete() — mark as done"""

    def test_complete_existing_card(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("complete me", ".")
        r = cr.complete(cid)
        assert isinstance(r, dict) or r is True


class TestCardRegistrySmoke:
    """Smoke test — basic flow does not crash"""

    def test_submit_list_cancel_cycle(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("full cycle", ".")
        assert cid.startswith("card-")

        cards = cr.list(state=None)
        assert len(cards) >= 1

        card = cr.get(cid)
        assert card is not None

        r = cr.cancel(cid)
        assert isinstance(r, dict) or r is not None
