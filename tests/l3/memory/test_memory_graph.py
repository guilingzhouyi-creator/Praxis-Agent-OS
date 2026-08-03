"""R5 群域图记忆（MemoryGraph）测试。

覆盖：开关（默认关/开启）、规则建边（sequential/type_chain/cell_chain）、
扩散检索、图约简报告、归因（created_by）、清理、MemoryManager 挂钩。

所有测试走生产路径：MemoryManager 挂钩 → get_graph() 单例。
"""

from l3.memory.memory import MemoryManager, reset_memory
from l3.memory.memory_graph import get_graph, reset_graph


def _activate_graph(tmp_path, enabled: bool = True):
    """Reset and activate the singleton graph on a temp DB."""
    reset_graph()
    g = get_graph(db_path=str(tmp_path / "graph_test.db"))
    g.set_enabled(enabled)
    return g


def test_disabled_by_default(tmp_path):
    reset_graph()
    g = get_graph(db_path=str(tmp_path / "g1.db"))
    assert g.enabled is False  # settings default


def test_enabled_switch_controls_edge_building(tmp_path):
    _activate_graph(tmp_path, enabled=False)
    mgr = MemoryManager()
    e1 = mgr.remember("a1", "decision", "first decision", ring=3)
    e2 = mgr.remember("a1", "decision", "second decision", ring=3)
    g = get_graph()
    assert g.stats()["edges"] == 0
    g.set_enabled(True)
    e3 = mgr.remember("a1", "decision", "third decision", ring=3)
    assert g.stats()["edges"] >= 1
    assert not e1.startswith("REJECTED") and not e2.startswith("REJECTED")
    assert not e3.startswith("REJECTED")


def test_rule_edges_sequential_and_type_chain(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    mgr.remember("a1", "decision", "decision one", ring=3)
    mgr.remember("a1", "decision", "decision two", ring=3)
    mgr.remember("a1", "summary", "session summary", ring=3)
    st = get_graph().stats()
    assert st["edges"] >= 2
    by_rel = st["by_relation"]
    assert by_rel.get("sequential", 0) >= 2
    assert by_rel.get("type_chain", 0) >= 1


def test_cell_chain_edge(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    mgr.remember("a1", "decision", "cell decision", ring=3, cell_id="cell-x")
    mgr.remember("a2", "decision", "cell decision 2", ring=3, cell_id="cell-x")
    st = get_graph().stats()
    assert st["by_relation"].get("cell_chain", 0) >= 1


def test_diffusion_recall(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    e1 = mgr.remember("a1", "decision", "root decision", ring=3)
    e2 = mgr.remember("a1", "decision", "followup", ring=3)
    mgr.remember("a1", "summary", "wrap up", ring=3)
    r = get_graph().recall([e1], depth=2, limit=10)
    assert r["stats"]["reached"] >= 3
    assert e2 in r["nodes"]
    assert r["edges"]


def test_disabled_recall_returns_empty(tmp_path):
    _activate_graph(tmp_path, enabled=False)
    mgr = MemoryManager()
    e1 = mgr.remember("a1", "decision", "x", ring=3)
    r = get_graph().recall([e1], depth=2)
    assert r["nodes"] == [] and r["stats"]["reached"] == 0


def test_compact_report_identifies_hubs(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    hub = mgr.remember("a1", "decision", "hub decision", ring=3)
    for i in range(4):
        mgr.remember("a1", "decision", f"leaf {i}", ring=3)
    rep = get_graph().compact_report(min_degree=2)
    assert rep["edges"] >= 4
    assert any(h["entry_id"] == hub for h in rep["hubs"])
    assert rep["leaves"] >= 0


def test_edge_attribution(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    e1 = mgr.remember("a1", "decision", "attributed", ring=3)
    mgr.remember("a1", "decision", "attributed 2", ring=3)
    edges = get_graph().edges_of(e1)
    assert edges and all(ed["created_by"] == "a1" for ed in edges)


def test_clear(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    mgr.remember("a1", "decision", "clear me", ring=3)
    mgr.remember("a1", "decision", "clear me 2", ring=3)
    g = get_graph()
    assert g.stats()["edges"] >= 1
    removed = g.clear()
    assert removed >= 1
    assert g.stats()["edges"] == 0


def test_manager_hook_produces_edges(tmp_path):
    """挂钩走单例生产路径，建边生效。"""
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    eid = mgr.remember("a1", "decision", "hook works", ring=3)
    assert not eid.startswith("REJECTED")
    mgr.remember("a1", "decision", "hook works 2", ring=3)
    st = get_graph().stats()
    assert st["edges"] >= 1


def test_no_self_loop(tmp_path):
    """首条 entry 不应产生自环边。"""
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    mgr.remember("a1", "decision", "first only", ring=3)
    st = get_graph().stats()
    assert st["edges"] == 0  # 只有一条 entry → 无边
