"""Tests for api_handlers_cards.py — extracted card API handlers."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_module_imports():
    from l4.api_handlers_cards import list_cards, get_card, submit_card
    assert callable(list_cards)
    assert callable(get_card)
    assert callable(submit_card)


def test_submit_batch_import():
    from l4.api_handlers_cards import submit_batch, card_rollback
    assert callable(submit_batch)
    assert callable(card_rollback)


def test_extra_imports():
    from l4.api_handlers_cards import card_gate_history, sideload_dispatch
    assert callable(card_gate_history)
    assert callable(sideload_dispatch)
