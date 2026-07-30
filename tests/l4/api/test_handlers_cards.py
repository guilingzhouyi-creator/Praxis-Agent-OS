"""API card handlers — list, get, submit, batch, rollback, gate history."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCardHandlers:
    def test_list_cards_importable(self):
        from l4.api.api_handlers_cards import list_cards
        assert callable(list_cards)

    def test_get_card_importable(self):
        from l4.api.api_handlers_cards import get_card
        assert callable(get_card)

    def test_submit_card_importable(self):
        from l4.api.api_handlers_cards import submit_card
        assert callable(submit_card)

    def test_submit_batch_importable(self):
        from l4.api.api_handlers_cards import submit_batch
        assert callable(submit_batch)

    def test_card_rollback_importable(self):
        from l4.api.api_handlers_cards import card_rollback
        assert callable(card_rollback)

    def test_card_gate_history_importable(self):
        from l4.api.api_handlers_cards import card_gate_history
        assert callable(card_gate_history)

    def test_sideload_dispatch_importable(self):
        from l4.api.api_handlers_cards import sideload_dispatch
        assert callable(sideload_dispatch)
