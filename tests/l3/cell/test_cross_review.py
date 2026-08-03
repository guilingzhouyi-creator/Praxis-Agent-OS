"""Tests for cell_cross_review.py — Cross-review after write operations."""
from __future__ import annotations

from l3.cell import get_cell, reset_cells
from l3.cell.components.cell_cross_review import auto_cross_review


def test_cross_review_skip_read_actions():
    """Cross-review is not triggered for non-write actions."""
    reset_cells()
    cell = get_cell("cr-cell-1", territory=["src"])
    result = auto_cross_review(cell, "agent-a", "read_file", "/test/path", "card-1")
    assert result["approved"] is True
    assert result["action"] == "skip"


def test_cross_review_skip_empty_target():
    """Cross-review is skipped when target is empty."""
    reset_cells()
    cell = get_cell("cr-cell-2", territory=["src"])
    result = auto_cross_review(cell, "agent-a", "write_file", "", "card-2")
    assert result["approved"] is True


def test_cross_review_skip_non_peer():
    """Cross-review is skipped when the agent is not a peer."""
    reset_cells()
    cell = get_cell("cr-cell-3", territory=["src"])
    result = auto_cross_review(cell, "scout-1", "write_file", "/test/path", "card-3")
    assert result["approved"] is True


def test_cross_review_no_peers():
    """Cross-review approves immediately when no other peers exist."""
    reset_cells()
    cell = get_cell("cr-cell-4", territory=["src"])
    cell.add_agent("agent-a", role="writer")
    result = auto_cross_review(cell, "agent-a", "write_file", "/test/path", "card-4")
    assert result["approved"] is True
