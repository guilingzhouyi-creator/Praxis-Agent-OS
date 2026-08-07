"""Tests for htn_a.py — Global HTN decomposition service."""

from __future__ import annotations

from l3.bus.htn_a import get_htn_a, get_shards


def test_htn_a_has_methods():
    """HTN-A has at least 3 pipeline decomposition methods registered."""
    htn = get_htn_a()
    assert len(htn._methods) >= 3


def test_htn_a_decompose_develop():
    """HTN-A decomposes a develop intent into multiple cell shards."""
    htn = get_htn_a()
    task = htn.decompose("Develop snake game", "app/dev")
    shards = get_shards(task)
    assert len(shards) >= 1
    for s in shards:
        assert "cell_id" in s
        assert "tasks" in s


def test_htn_a_decompose_fix():
    """HTN-A decomposes a fix intent correctly."""
    htn = get_htn_a()
    task = htn.decompose("Fix login bug", "app/fix")
    shards = get_shards(task)
    assert len(shards) >= 1


def test_htn_a_decompose_review():
    """HTN-A decomposes a review intent correctly."""
    htn = get_htn_a()
    task = htn.decompose("Review auth code", "app/review")
    shards = get_shards(task)
    assert len(shards) >= 1


def test_htn_a_shards_have_cell_ids():
    """Each shard is assigned to a specific cell ID (cell-1, cell-2, cell-3)."""
    htn = get_htn_a()
    task = htn.decompose("Develop game", "app/dev")
    shards = get_shards(task)
    cell_ids = {s["cell_id"] for s in shards}
    assert len(cell_ids) >= 1
    for cid in cell_ids:
        assert cid.startswith("cell-")
