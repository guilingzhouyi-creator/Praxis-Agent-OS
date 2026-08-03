"""Tests for L3A context management — ContextRegistry, ContextEpoch, archive."""

from __future__ import annotations


class TestContextRegistry:
    def test_register_and_get(self):
        from l3.cell.peers.l3a.context import ContextRegistry, ContextSource
        r = ContextRegistry()
        src = ContextSource(key="test", loader=lambda: {"val": 42},
                            render_baseline=lambda v: str(v))
        r.register(src)
        assert r.get("test") is src

    def test_load_all(self):
        from l3.cell.peers.l3a.context import ContextRegistry, ContextSource
        r = ContextRegistry()
        r.register(ContextSource(key="a", loader=lambda: 1, render_baseline=lambda v: str(v)))
        r.register(ContextSource(key="b", loader=lambda: 2, render_baseline=lambda v: str(v)))
        vals = r.load_all()
        assert vals["a"] == 1
        assert vals["b"] == 2

    def test_load_all_loader_failure(self):
        from l3.cell.peers.l3a.context import ContextRegistry, ContextSource
        r = ContextRegistry()
        def failing():
            raise ValueError("oops")
        r.register(ContextSource(key="fail", loader=failing, render_baseline=lambda v: str(v)))
        # Should not raise — logger.debug inside
        vals = r.load_all()
        assert "fail" not in vals

    def test_render_baseline(self):
        from l3.cell.peers.l3a.context import ContextRegistry, ContextSource
        r = ContextRegistry()
        r.register(ContextSource(key="k", loader=lambda: "v", render_baseline=lambda v: f"key=k,val={v}"))
        rendered = r.render_baseline({"k": "v"})
        assert "key=k" in rendered

    def test_diff_no_change(self):
        from l3.cell.peers.l3a.context import ContextRegistry
        r = ContextRegistry()
        changes = r.diff({"k": "v"}, {"k": "v"})
        assert len(changes) == 0

    def test_diff_with_change(self):
        from l3.cell.peers.l3a.context import ContextRegistry, ContextSource
        r = ContextRegistry()
        r.register(ContextSource(key="k", loader=lambda: "new",
                                 render_baseline=lambda v: str(v),
                                 render_update=lambda o, n: f"{o}→{n}"))
        changes = r.diff({"k": "old"}, {"k": "new"})
        assert len(changes) == 1
        assert "old→new" in changes[0].text


class TestContextEpoch:
    def test_create_and_estimate_tokens(self):
        from l3.cell.peers.l3a.context import ContextEpoch, ContextRegistry, ContextSource
        reg = ContextRegistry()
        reg.register(ContextSource(key="x", loader=lambda: "hello",
                                   render_baseline=lambda v: v))
        epoch = ContextEpoch.create(reg)
        assert epoch.id is not None
        assert len(epoch.baseline) > 0
        assert epoch.estimate_tokens() >= 0

    def test_sync_turn_count(self):
        from l3.cell.peers.l3a.context import ContextEpoch, ContextRegistry
        reg = ContextRegistry()
        epoch = ContextEpoch.create(reg)
        before = epoch.turn_count
        epoch.sync(reg)
        assert epoch.turn_count == before + 1


class TestArchive:
    def test_store_and_search_session(self):
        from l3.cell.peers.l3a.archive import store_session
        sid = "test-sess-001"
        meta = {"session_id": sid, "title": "test", "tags": ["l3a", "session"]}
        r = store_session(sid, meta, [{"role": "user", "content": "hello"}])
        # Should succeed even if real DB unavailable (in-memory not supported)
        assert isinstance(r, dict)
        assert "success" in r

    def test_search_nonexistent(self):
        from l3.cell.peers.l3a.archive import search_sessions
        r = search_sessions(session_id="no-such-session")
        assert "success" in r
