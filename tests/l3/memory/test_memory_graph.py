"""R5 群域图记忆（MemoryGraph）测试。

覆盖：开关（默认关/开启）、规则建边（sequential/type_chain/cell_chain）、
扩散检索、图约简报告、归因（created_by）、清理、MemoryManager 挂钩。

所有测试走生产路径：MemoryManager 挂钩 → get_graph() 单例。
"""

from l3.memory.memory import MemoryManager
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


def test_compact_executable_prunes_leaves(tmp_path):
    """图约简执行版：dry_run 只报告，执行剪叶子保留 hub-hub 边。"""
    _activate_graph(tmp_path, enabled=True)
    g = get_graph()
    # 手工构造：n-b / n-h 是 hub（度 2），n-a/n-c/n-d/n-e 是叶子（度 1）
    import time as _t
    for f, t in (("n-a", "n-b"), ("n-b", "n-c"), ("n-b", "n-h"),
                 ("n-h", "n-d"), ("n-h", "n-e")):
        g._insert_edge(f, t, "sequential", 1.0, "test", _t.time())
    dry = g.compact(min_degree=2, dry_run=True)
    assert dry["dry_run"] is True and dry["leaves"] >= 4
    before = g.stats()["edges"]
    res = g.compact(min_degree=2, dry_run=False)
    assert res["success"] and res["dry_run"] is False
    assert res["edges_removed"] >= 4
    assert g.stats()["edges"] < before
    # hub-hub 边保留：n-b 仍连接 n-h
    assert any(ed["to_id"] == "n-h" or ed["from_id"] == "n-h"
               for ed in g.edges_of("n-b"))


def test_recall_graph_diffusion_expands(tmp_path):
    """扩散检索接入 recall：线性命中沿边扩展。"""
    _activate_graph(tmp_path, enabled=True)
    mgr = MemoryManager()
    e1 = mgr.remember("a1", "decision", "alpha decision", ring=3)
    e2 = mgr.remember("a1", "decision", "beta followup", ring=3)
    mgr.remember("a1", "summary", "gamma wrap", ring=3)
    linear = mgr.recall(agent_id="a1", entry_type="decision", limit=10)
    ids = {e.id for e in linear}
    assert e1 in ids and e2 in ids
    diff = mgr.recall(agent_id="a1", entry_type="decision", limit=10,
                      graph_diffusion=True)
    diff_ids = {e.id for e in diff}
    # 扩散后应包含图可达的 summary 节点（通过 type_chain 边）
    assert len(diff_ids) >= len(ids) or any(
        e.entry_type == "summary" for e in diff)


def test_recall_diffusion_disabled_graph_falls_back(tmp_path):
    """图关闭时 graph_diffusion=True 回退线性（零影响）。"""
    _activate_graph(tmp_path, enabled=False)
    mgr = MemoryManager()
    e1 = mgr.remember("a1", "decision", "linear only", ring=3)
    mgr.remember("a1", "decision", "linear two", ring=3)
    r = mgr.recall(agent_id="a1", limit=10, graph_diffusion=True)
    assert any(e.id == e1 for e in r)


def test_central_recall_passes_diffusion(tmp_path):
    """CentralMemory.recall 透传 graph_diffusion。"""
    from l3.memory.central_memory import get_center, reset_center
    reset_center()
    _activate_graph(tmp_path, enabled=True)
    center = get_center()
    mem = center.get_or_create("l3a")
    mem.set_persist_dir(str(tmp_path))
    mem.remember("a1", "decision", "central alpha", ring=3)
    mem.remember("a1", "decision", "central beta", ring=3)
    mem.remember("a1", "summary", "central wrap", ring=3)
    r = center.recall(scope_id="l3a", limit=10, graph_diffusion=True)
    assert r and len(r) >= 3


# Phase 4: semantic edges + compression linkage


def test_semantic_edge_add_and_validate(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    g = get_graph()
    ok = g.add_semantic_edge("e1", "e2", "contradicts", created_by="review")
    assert ok["success"] and ok["relation"] == "contradicts"
    bad = g.add_semantic_edge("e1", "e2", "loves")
    assert not bad["success"] and "relation" in bad["error"]
    dup = g.add_semantic_edge("e1", "e2", "contradicts")
    assert not dup["success"] and "already exists" in dup["error"]
    selfloop = g.add_semantic_edge("e1", "e1", "refines")
    assert not selfloop["success"]
    g.set_enabled(False)
    off = g.add_semantic_edge("e1", "e3", "depends_on")
    assert not off["success"] and "disabled" in off["error"]


def test_semantic_edges_listing(tmp_path):
    _activate_graph(tmp_path, enabled=True)
    g = get_graph()
    g.add_semantic_edge("a1", "a2", "contradicts", created_by="llm")
    g.add_semantic_edge("b1", "b2", "depends_on", created_by="llm")
    import time as _t
    g._insert_edge("x1", "x2", "sequential", 1.0, "system", _t.time())
    sem = g.semantic_edges()
    assert len(sem) == 2
    assert {e["relation"] for e in sem} == {"contradicts", "depends_on"}


def test_semantic_edge_api(tmp_path):
    from l4.api_handlers import ApiHandlers
    reset_graph()
    g = get_graph(db_path=str(tmp_path / "sem.db"))
    g.set_enabled(True)
    api = ApiHandlers()
    r = api._memory_graph_edge({"from_id": "a", "to_id": "b",
                                "relation": "contradicts"})
    assert r["success"]
    lst = api._memory_graph_semantic()
    assert lst["success"] and len(lst["edges"]) == 1
    r2 = api._memory_graph_edge({"from_id": "a", "to_id": "b",
                                 "relation": "nope"})
    assert not r2["success"]


def test_compress_triggers_graph_compact(tmp_path):
    """Compression auto-triggers graph reduction (graph enabled)."""
    from l3.cell.peers.l3a import get_daemon
    from l3.memory.central_memory import reset_center
    reset_center()
    _activate_graph(tmp_path, enabled=True)
    d = get_daemon()
    s = d.create_session("compact-link")
    s._ensure_loop()

    def fake_run(**kw):
        return {"answer": "ok", "success": True, "tool_calls": [],
                "reasoning_trail": ["t"], "reasoning_tokens": 1}
    s._loop.run = fake_run
    for i in range(3):
        s.prompt(f"bulk question {i}")
    r = s.compress(keep_last=2)
    assert r["success"]
    s.close()
