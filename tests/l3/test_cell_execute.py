"""Tests for cell_execute.py — Cell execute_card, decompose, snapshot logic."""
from __future__ import annotations

import pytest
from l3.cell import get_cell, reset_cells
from l3.cell.components.cell_execute import execute_card, _raw_to_card, _take_snapshot


def test_execute_card_raw_string():
    """execute_card accepts a raw intent string and returns a result dict."""
    reset_cells()
    cell = get_cell("test-cell", territory=["src"])
    result = execute_card(cell, "test intent")
    assert isinstance(result, dict)
    assert "card_id" in result or "success" in result


def test_execute_card_handles_issue():
    """execute_card routes IssueCard to convention protocol."""
    reset_cells()
    cell = get_cell("test-cell-2", territory=["src"])
    from l3.issue import IssueCard
    card = IssueCard(title="test issue", intent="fix bug", domain="src")
    result = execute_card(cell, card)
    assert isinstance(result, dict)


def test_raw_to_card_returns_card():
    """_raw_to_card converts a string to a Card object."""
    reset_cells()
    cell = get_cell("test-cell-3", territory=["src"])
    card = _raw_to_card(cell, "simple task", "src")
    assert card is not None
    assert hasattr(card, "phases") or hasattr(card, "intent")


def test_raw_to_card_skip_htn():
    """_raw_to_card with skip_htn=True bypasses HTN decomposition."""
    reset_cells()
    cell = get_cell("test-cell-4", territory=["src"])
    card = _raw_to_card(cell, "test", "src", skip_htn=True)
    assert card is not None


def test_take_snapshot_nonexistent_file():
    """_take_snapshot returns None for non-existent paths."""
    snapshot = _take_snapshot("/nonexistent/path.txt")
    assert snapshot is None


def test_execute_card_empty_territory():
    """execute_card works with empty territory."""
    reset_cells()
    cell = get_cell("test-cell-5", territory=[])
    result = execute_card(cell, "simple task")
    assert isinstance(result, dict)
