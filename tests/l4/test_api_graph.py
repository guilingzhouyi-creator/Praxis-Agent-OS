"""R5 群域图 API 端点测试（前端可切换开关）。

覆盖：GET/PUT /api/memory/graph（状态/切换）、compact 端点
（小图保护）、recall graph_diffusion 透传。
"""

import pytest

from l3.memory.memory import MemoryManager, reset_memory
from l3.memory.memory_graph import get_graph, reset_graph
from l3.memory.central_memory import get_center, reset_center
from l4.api_handlers import ApiHandlers


@pytest.fixture
def graph_api(tmp_path):
    reset_memory()
    reset_center()
    reset_graph()
    g = get_graph(db_path=str(tmp_path / "api_graph.db"))
    g.set_enabled(False)
    api = ApiHandlers()
    center = get_center()
    mgr = MemoryManager()
    center.register("l3a", mgr)
    return api, mgr, g


def test_graph_status_disabled(graph_api):
    api, _, _ = graph_api
    r = api._memory_graph_status()
    assert r["success"] and r["enabled"] is False
    assert "stats" in r and "compact" in r


def test_graph_set_enables_and_persists(graph_api):
    api, mgr, g = graph_api
    r = api._memory_graph_set({"enabled": True})
    assert r["success"] and r["enabled"] is True
    assert g.enabled is True
    mgr.remember("a1", "decision", "enabled entry", ring=3)
    st = api._memory_graph_status()
    assert st["enabled"] is True


def test_graph_set_requires_enabled_key(graph_api):
    api, _, _ = graph_api
    r = api._memory_graph_set({})
    assert not r["success"] and "enabled" in r["error"]


def test_graph_compact_small_graph_guard(graph_api):
    api, mgr, _ = graph_api
    api._memory_graph_set({"enabled": True})
    mgr.remember("a1", "decision", "one", ring=3)
    mgr.remember("a1", "decision", "two", ring=3)
    dry = api._memory_graph_compact({"dry_run": True})
    assert dry["success"] and dry["dry_run"] is True
    res = api._memory_graph_compact({"dry_run": False})
    assert res["success"] is False  # 图太小保护
    assert "too small" in res["error"]


def test_graph_compact_big_graph_prunes(graph_api):
    api, mgr, _ = graph_api
    api._memory_graph_set({"enabled": True})
    for i in range(6):
        mgr.remember("a1", "decision", f"bulk {i}", ring=3)
    res = api._memory_graph_compact({"dry_run": False, "min_degree": 2})
    assert res["success"] and res["dry_run"] is False


def test_memory_recall_diffusion_passthrough(graph_api):
    api, mgr, _ = graph_api
    api._memory_graph_set({"enabled": True})
    for i in range(4):
        mgr.remember("a1", "decision", f"recall {i}", ring=3)
    mgr.remember("a1", "summary", "wrap", ring=3)
    r = api._memory_recall({"agent_id": "a1", "limit": 10,
                            "graph_diffusion": True})
    assert r["success"] and r["count"] >= 5
    r2 = api._memory_recall({"agent_id": "a1", "limit": 10})
    assert r2["success"] and r2["count"] >= 5


def test_graph_disable_zero_impact(graph_api):
    api, mgr, g = graph_api
    api._memory_graph_set({"enabled": True})
    mgr.remember("a1", "decision", "before", ring=3)
    edges_before = g.stats()["edges"]
    api._memory_graph_set({"enabled": False})
    mgr.remember("a1", "decision", "after", ring=3)
    assert g.stats()["edges"] == edges_before  # 关闭后不再建边
    r = api._memory_graph_status()
    assert r["enabled"] is False
