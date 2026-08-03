"""Tests for api_handlers_cluster.py — Cluster management API handlers."""
from __future__ import annotations

from l4.api_handlers.api_handlers_cluster import cluster_composites, cluster_expand, cluster_shrink, cluster_status


def test_cluster_status_returns_dict():
    """cluster_status returns a dict with state information."""
    result = cluster_status()
    assert isinstance(result, dict)
    assert "success" in result
    assert "state" in result


def test_cluster_status_has_cell_count():
    """cluster_status includes cell_count and composite_count."""
    result = cluster_status()
    assert "cell_count" in result
    assert "composite_count" in result


def test_cluster_composites_returns_list():
    """cluster_composites returns a list of composites."""
    result = cluster_composites()
    assert isinstance(result, dict)
    assert "composites" in result
    assert isinstance(result["composites"], list)


def test_cluster_expand_requires_cell_id():
    """cluster_expand returns error when cell_id is missing."""
    result = cluster_expand({})
    assert result.get("success") is False
    assert "cell_id required" in result.get("error", "")


def test_cluster_shrink_requires_cell_id():
    """cluster_shrink returns error when cell_id is missing."""
    result = cluster_shrink({})
    assert result.get("success") is False
    assert "cell_id required" in result.get("error", "")
