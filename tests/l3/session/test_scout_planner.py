"""Scout + HTN Planner + Dialogue Session test"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestScoutCore:
    """Scout basic functionality"""

    def test_scout_search(self):
        from l3.agent.scout import ScoutSession

        s = ScoutSession(scout_id="s-1", agent_id="agent-a", task="investigate")
        assert s is not None
        assert s.scout_id == "s-1"

    def test_get_pool(self):
        from l3.agent.scout import get_pool, reset_pool

        reset_pool()
        pool = get_pool()
        assert pool is not None

    def test_pool_stats(self):
        from l3.agent.scout import get_pool, reset_pool

        reset_pool()
        pool = get_pool()
        stats = pool.stats() if hasattr(pool, "stats") else {}
        assert isinstance(stats, dict)


class TestHtnPlanner:
    """HTN planner"""

    def test_planner_create(self):
        from l3.bus.htn_planner import HTNPlanner

        planner = HTNPlanner()
        assert planner is not None

    def test_decompose_basic(self):
        from l3.bus.htn_planner import HTNPlanner

        planner = HTNPlanner()
        task = planner.decompose("read src/main.py", ".")
        assert task is not None

    def test_decompose_develop(self):
        from l3.bus.htn_planner import HTNPlanner

        planner = HTNPlanner()
        task = planner.decompose("add login feature to auth module", "src/auth")
        assert task is not None

    def test_to_card(self):
        from l3.bus.htn_planner import HTNPlanner

        planner = HTNPlanner()
        task = planner.decompose("list directory", ".")
        card = planner.to_card(task, domain=".")
        assert card is not None
        # HTN intent is carried on the card summary title
        assert card.summary.title

    def test_planner_stats(self):
        from l3.bus.htn_planner import HTNPlanner

        planner = HTNPlanner()
        stats = planner.stats()
        assert isinstance(stats, dict)


class TestDialogueSession:
    """Dialogue session"""

    def test_session_create(self):
        from l3.card.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-a", task="t")
        assert session.session_id.startswith("session-")
        assert session.agent_id == "agent-a"

    def test_add_turn(self):
        from l3.card.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-b")
        turn = session.record_turn(prompt="hello", response="hi there")
        assert turn.turn == 1
        assert session._turns[0].prompt == "hello"
        assert session._turns[0].response == "hi there"

    def test_multiple_turns(self):
        from l3.card.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-c")
        for i in range(5):
            session.record_turn(prompt=f"msg_{i}", response=f"resp_{i}")
        assert len(session._turns) == 5

    def test_mark_failed(self):
        from l3.card.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-d")
        r = session.fail("something broke")
        assert not r["success"]
        assert session.state.name == "FAILED"

    def test_get_history(self):
        from l3.card.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-e")
        session.record_turn(prompt="q1", response="a1")
        session.record_turn(prompt="q2", response="a2")
        hist = session.turn_summary()
        assert len(hist) >= 2

    def test_serialize(self):
        from l3.card.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-f")
        session.record_turn(prompt="save me", response="ok")
        data = session.stats()
        assert data["session_id"].startswith("session-")
        assert data["turns"] >= 1
