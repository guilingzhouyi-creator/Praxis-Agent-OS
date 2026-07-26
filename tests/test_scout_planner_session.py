"""Scout + HTN Planner + Dialogue Session test"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestScoutCore:
    """Scout basic functionality"""

    def test_scout_search(self):
        from services.scout import Scout
        s = Scout()
        assert s is not None

    def test_get_pool(self):
        from services.scout import get_pool, reset_pool
        reset_pool()
        pool = get_pool()
        assert pool is not None

    def test_pool_stats(self):
        from services.scout import get_pool, reset_pool
        reset_pool()
        pool = get_pool()
        stats = pool.stats() if hasattr(pool, 'stats') else {}
        assert isinstance(stats, dict)


class TestHtnPlanner:
    """HTN planner"""

    def test_planner_create(self):
        from services.htn_planner import get_service, HtnPlanner
        planner = HtnPlanner()
        assert planner is not None

    def test_decompose_basic(self):
        from services.htn_planner import HtnPlanner
        planner = HtnPlanner()
        task = planner.decompose("read src/main.py", ".")
        assert task is not None

    def test_decompose_develop(self):
        from services.htn_planner import HtnPlanner
        planner = HtnPlanner()
        task = planner.decompose("add login feature to auth module", "src/auth")
        assert task is not None

    def test_to_card(self):
        from services.htn_planner import HtnPlanner
        planner = HtnPlanner()
        task = planner.decompose("list directory", ".")
        card = planner.to_card(task, domain=".")
        assert card is not None
        assert hasattr(card, 'intent')

    def test_planner_stats(self):
        from services.htn_planner import HtnPlanner
        planner = HtnPlanner()
        stats = planner.stats()
        assert isinstance(stats, dict)


class TestDialogueSession:
    """对话会话"""

    def test_session_create(self):
        from services.dialogue_session import DialogueSession
        session = DialogueSession(session_id="sess-test", agent_id="agent-a")
        assert session.session_id == "sess-test"
        assert session.agent_id == "agent-a"

    def test_add_turn(self):
        from services.dialogue_session import DialogueSession
        session = DialogueSession(session_id="sess-turn", agent_id="agent-b")
        session.add_turn(prompt="hello", response="hi there")
        assert len(session._turns) == 1
        assert session._turns[0]["prompt"] == "hello"
        assert session._turns[0]["response"] == "hi there"

    def test_multiple_turns(self):
        from services.dialogue_session import DialogueSession
        session = DialogueSession(session_id="sess-multi", agent_id="agent-c")
        for i in range(5):
            session.add_turn(prompt=f"msg_{i}", response=f"resp_{i}")
        assert len(session._turns) == 5

    def test_mark_failed(self):
        from services.dialogue_session import DialogueSession
        session = DialogueSession(session_id="sess-fail", agent_id="agent-d")
        r = session.mark_failed("something broke")
        assert not r["success"]
        assert session.state.name == "FAILED"

    def test_get_history(self):
        from services.dialogue_session import DialogueSession
        session = DialogueSession(session_id="sess-hist", agent_id="agent-e")
        session.add_turn(prompt="q1", response="a1")
        session.add_turn(prompt="q2", response="a2")
        hist = session.get_history()
        assert len(hist) >= 2

    def test_serialize(self):
        from services.dialogue_session import DialogueSession
        session = DialogueSession(session_id="sess-serial", agent_id="agent-f")
        session.add_turn(prompt="save me", response="ok")
        data = session.serialize()
        assert data["session_id"] == "sess-serial"
        assert len(data["turns"]) >= 1
