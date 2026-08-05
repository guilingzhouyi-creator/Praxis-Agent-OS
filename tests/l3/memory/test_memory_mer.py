"""Mer 符号化记忆旁路（memory_mer）测试。

覆盖：开关、Mermaid 生成、多 scope 聚合、R4 归档、API 端点、daemon tick 联动。
"""

from l3.memory.memory import MemoryManager, reset_memory
from l3.memory.memory_mer import MerTransformer, get_mer, reset_mer
from l3.memory.central_memory import get_center, reset_center


def _setup_memory(tmp_path) -> None:
    reset_memory()
    reset_center()
    center = get_center()
    for sid in ("l3a", "cell-a"):
        mem = MemoryManager()
        mem.set_persist_dir(str(tmp_path))
        mem.remember("a1", "decision", "high value decision one", ring=3,
                     importance=0.8)
        mem.remember("a1", "decision", "high value decision two", ring=3,
                     importance=0.7)
        mem.remember("a1", "summary", "low value noise", ring=3,
                     importance=0.2)
        center.register(sid, mem)


def test_mer_disabled_by_default(tmp_path):
    # API set 会持久化 settings——先重置避免跨测试污染
    try:
        from l3.config.settings_center import get_center as _sc
        _sc().set("memory.mer.enabled", False)
    except Exception:
        pass
    reset_mer()
    m = get_mer()
    assert m.enabled is False


def test_mer_collect_filters_by_importance(tmp_path):
    _setup_memory(tmp_path)
    m = MerTransformer(enabled=True)
    entries = m.collect_entries(scope_ids=["l3a", "cell-a"], limit=10)
    assert len(entries) >= 4  # 高价值条目被收集
    assert all(float(e["importance"]) >= 0.4 for e in entries)


def test_mer_to_mermaid(tmp_path):
    _setup_memory(tmp_path)
    m = MerTransformer(enabled=True)
    entries = m.collect_entries(scope_ids=["l3a"], limit=5)
    md = m.to_mermaid(entries, [], title="test")
    assert md.startswith("flowchart LR")
    assert "subgraph test" in md
    # decision -> diamond, summary -> round, content preview present
    assert "{decision:" in md or "(\"summary:" in md
    # importance label is rendered
    assert "imp=0." in md


def test_mer_mermaid_time_chain(tmp_path):
    """Within-scope chronological chains are dashed edges (no graph needed)."""
    _setup_memory(tmp_path)
    m = MerTransformer(enabled=True)
    entries = [
        {"id": "a", "entry_type": "decision", "content": "first",
         "importance": 0.8, "timestamp": 1.0, "_scope": "l3a"},
        {"id": "b", "entry_type": "decision", "content": "second",
         "importance": 0.8, "timestamp": 2.0, "_scope": "l3a"},
        {"id": "c", "entry_type": "summary", "content": "other scope",
         "importance": 0.8, "timestamp": 3.0, "_scope": "cell-a"},
    ]
    md = m.to_mermaid(entries, [], title="test")
    # temporal chain links a -> b in scope l3a; c is alone in its scope
    assert "e0 -.->|t| e1" in md
    assert "e1 -.->|t| e2" not in md
    # distinct shapes for decision vs summary
    assert "{decision:" in md
    assert "(\"summary:" in md


def test_mer_mermaid_includes_edges(tmp_path):
    from l3.memory.memory_graph import get_graph, reset_graph
    reset_graph()
    g = get_graph(db_path=str(tmp_path / "mer_graph.db"))
    g.set_enabled(True)
    _setup_memory(tmp_path)
    g.add_semantic_edge("m1", "m2", "contradicts")
    m = MerTransformer(enabled=True)
    # 手工构造节点 id 与边匹配的条目
    entries = [
        {"id": "m1", "entry_type": "decision", "content": "use JWT",
         "importance": 0.8, "timestamp": 1.0},
        {"id": "m2", "entry_type": "decision", "content": "drop JWT",
         "importance": 0.8, "timestamp": 2.0},
    ]
    edges = m.collect_edges(["m1", "m2"])
    md = m.to_mermaid(entries, edges)
    assert "-->|contradicts|" in md


def test_mer_transform_and_archive(tmp_path):
    _setup_memory(tmp_path)
    m = MerTransformer(enabled=True)
    r = m.transform_and_archive(scope_ids=["l3a", "cell-a"])
    assert r["success"] and r["archived"] == 1
    assert r["entries"] >= 4
    assert r["mermaid"].startswith("flowchart LR")
    assert r["archive_ref"]


def test_mer_disabled_transform_refused(tmp_path):
    m = MerTransformer(enabled=False)
    r = m.transform_and_archive()
    assert not r["success"] and "disabled" in r["error"]


def test_mer_api_endpoints(tmp_path):
    from l4.api_handlers import ApiHandlers
    reset_mer()
    api = ApiHandlers()
    st = api._memory_mer_status()
    assert st["success"] and "mer" in st
    r = api._memory_mer_set({"enabled": True})
    assert r["success"] and r["enabled"] is True
    _setup_memory(tmp_path)
    r = api._memory_mer_transform({"scope_ids": ["l3a"]})
    assert r["success"] and r["archived"] >= 1


def test_mer_daemon_tick_linkage(tmp_path):
    """daemon tick 在开关开启时触发 Mer 旁路。"""
    from l3.cell.peers.l3a import get_daemon
    from l3.memory.memory_mer import reset_mer, get_mer
    reset_center()
    reset_mer()
    m = get_mer()
    m.set_enabled(True)
    _setup_memory(tmp_path)
    d = get_daemon()
    r = d.tick()
    # tick 不抛异常（Mer 在 tick 内静默执行）
    assert isinstance(r, dict)
    m.set_enabled(False)
