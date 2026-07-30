"""Integration tests for L3A — full lifecycle: create → prompt → close."""

from __future__ import annotations


class TestL3AIntegration:
    def test_session_create_and_close(self):
        from l3.cell.peers.l3a.session import Session
        s = Session.create(title="integration-test")
        info = s.info()
        assert info["status"] == "active"
        r = s.close()
        assert r["success"] is True

    def test_session_messages_after_close(self):
        from l3.cell.peers.l3a.session import Session
        s = Session.create(title="msg-test")
        s.close()
        page = s.messages(limit=5)
        assert page.total == 0

    def test_session_create_with_model_config(self):
        from l3.cell.peers.l3a.session import Session
        from l3.cell.peers.l3a.model import L3AModelConfig
        cfg = L3AModelConfig(provider="ollama", model="qwen2.5")
        s = Session.create(title="cfg-test", model_config=cfg)
        info = s.info()
        assert info["model"]["provider"] == "ollama"
        s.close()

    def test_inbox_full_flow(self):
        from l3.cell.peers.l3a.session import Session
        s = Session.create(title="inbox-flow")
        inbox = s.inbox
        inbox.admit("first prompt", mode="steer")
        inbox.admit("second prompt", mode="queue")
        assert inbox.pending_count() == 2
        p1 = inbox.promote()
        assert p1.text == "first prompt"
        p2 = inbox.promote()
        assert p2.text == "second prompt"
        assert inbox.pending_count() == 0
        s.close()

    def test_session_history_project(self):
        from l3.cell.peers.l3a.session import Session, Message
        s = Session.create(title="hist-test")
        s.history.extend([
            Message(id="m1", role="user", content="q1", created_at=1.0),
            Message(id="m2", role="assistant", content="a1", created_at=2.0),
        ])
        assert s.history.count() == 2
        projected = s.history.project(max_tokens=32000)
        assert len(projected) == 2
        s.close()

    def test_context_registry_diff(self):
        from l3.cell.peers.l3a.context import ContextRegistry, ContextSource
        reg = ContextRegistry()
        reg.register(ContextSource(
            key="test", loader=lambda: {"val": 1},
            render_baseline=lambda v: str(v),
            render_update=lambda o, n: f"{o['val']}→{n['val']}",
        ))
        # Load baseline
        vals = reg.load_all()
        baseline = reg.render_baseline(vals)
        assert len(baseline) > 0
        # Diff with unchanged
        changes = reg.diff(vals, reg.load_all())
        assert len(changes) == 0

    def test_subagent_pool_commission_and_peek(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool
        pool = L3ASubAgentPool(max_workers=2)
        r = pool.commission(spec="investigator", task="examine files", group="g-int")
        assert r["success"] is True
        tid = r["task_id"]
        peek = pool.peek(tid)
        assert peek["status"] in ("running", "done")
        pool.shutdown(wait=False)

    def test_daemon_get_pool(self):
        from l3.cell.peers.l3a.subagent import get_pool
        pool = get_pool()
        assert pool is not None
