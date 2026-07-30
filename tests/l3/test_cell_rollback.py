"""Tests for cell_rollback.py — Card rollback logic."""
from __future__ import annotations

import pytest
from l3.cell import get_cell, reset_cells
from l3.cell.components.cell_rollback import rollback_card


def test_rollback_card_empty_id():
    """rollback_card returns a dict with success flag for empty card_id."""
    reset_cells()
    cell = get_cell("rb-cell-1", territory=["src"])
    result = rollback_card(cell, card_id="")
    assert isinstance(result, dict)
    assert "success" in result
    assert "results" in result


def test_rollback_card_nonexistent():
    """rollback_card handles card_id that was never executed gracefully."""
    reset_cells()
    cell = get_cell("rb-cell-2", territory=["docs"])
    result = rollback_card(cell, card_id="card-nonexistent")
    assert isinstance(result, dict)
    assert "results" in result


def test_rollback_card_has_rollback_context():
    """rollback_card stores rollback context in the Cell's rollback ring."""
    reset_cells()
    cell = get_cell("rb-cell-3", territory=["src"])
    result = rollback_card(cell, card_id="card-test-1")
    assert "rollback_context" in result
    assert "Card" in result["rollback_context"]
