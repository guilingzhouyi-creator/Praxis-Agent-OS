"""l3a_ask clarification tool tests — state machine, session flow, command/API paths."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class _FakeLoop:
    """AgentLoop stand-in: records run invocations, never calls the LLM."""

    def __init__(self):
        self.runs = 0
        self.task = ""
        self._context_trail = []
        self._cached_system = ""

    def add_tool(self, *args, **kwargs):
        pass

    def run(self, **kwargs):
        self.runs += 1
        return {"answer": "resumed-ok", "tool_calls": []}


class TestAskState:
    def test_from_questions_caps_max(self):
        from l3.cell.peers.l3a.ask import AskState
        from l3.cell.peers.l3a.params import ASK_MAX_QUESTIONS

        st = AskState.from_questions([f"q{i}" for i in range(20)])
        assert len(st.questions) == ASK_MAX_QUESTIONS
        assert st.status == "awaiting"

    def test_from_questions_normalizes_dicts(self):
        from l3.cell.peers.l3a.ask import AskState

        st = AskState.from_questions(
            [
                {"id": "platform", "question": "Target platform?", "options": ["win", "linux"]},
                {"question": "Scope?", "required": False},
            ]
        )
        assert st.questions[0].id == "platform"
        assert st.questions[0].options == ["win", "linux"]
        assert st.questions[1].required is False
        assert st.questions[1].id == "q2"

    def test_roundtrip_serialization(self):
        from l3.cell.peers.l3a.ask import AskState

        st = AskState.from_questions([{"question": "A?"}, {"question": "B?"}])
        st.questions[0].answer = "yes"
        st.free_form = "extra"
        d = st.to_dict()
        st2 = AskState.from_dict(d)
        assert st2.questions[0].answer == "yes"
        assert st2.free_form == "extra"
        assert st2.status == "awaiting"

    def test_missing_required(self):
        from l3.cell.peers.l3a.ask import AskState

        st = AskState.from_questions([{"question": "A?"}, {"question": "B?", "required": False}])
        st.questions[0].answer = "x"
        assert st.missing() == []

    def test_missing_reports_unanswered(self):
        from l3.cell.peers.l3a.ask import AskState

        st = AskState.from_questions([{"question": "A?"}, {"question": "B?"}])
        st.questions[1].answer = "y"
        assert st.missing() == ["q1"]


class _FakeSession:
    """Minimal session stand-in for handler/state tests."""

    def __init__(self):
        self._ask = None
        self.history = []
        self.id = "l3a-test"
        self.turn_count = 0
        self._persisted = 0

    def _persist_state(self):
        self._persisted += 1


class TestAskHandler:
    def test_handler_sets_awaiting(self):
        from l3.cell.peers.l3a.ask import ask_handler

        s = _FakeSession()
        r = ask_handler(s, {"questions": ["Target platform?", "Deadline?"]})
        assert r["success"] is True
        assert r["awaiting_input"] is True
        assert r["asked"] == 2
        assert s._ask.status == "awaiting"

    def test_handler_requires_questions(self):
        from l3.cell.peers.l3a.ask import ask_handler

        r = ask_handler(_FakeSession(), {})
        assert r["success"] is False

    def test_submit_answers_full(self):
        from l3.cell.peers.l3a.ask import ask_handler, submit_answers

        s = _FakeSession()
        ask_handler(s, {"questions": ["A?", "B?"]})
        r = submit_answers(s, {"q1": "windows", "q2": "this week"})
        assert r["success"] is True
        assert r["answered"] == 2
        assert r["missing"] == []
        assert s._ask.status == "answered"

    def test_submit_answers_partial_reports_missing(self):
        from l3.cell.peers.l3a.ask import ask_handler, submit_answers

        s = _FakeSession()
        ask_handler(s, {"questions": ["A?", "B?"]})
        r = submit_answers(s, {"q1": "only this"})
        assert r["answered"] == 1
        assert r["missing"] == ["q2"]

    def test_submit_without_pending_fails(self):
        from l3.cell.peers.l3a.ask import submit_answers

        r = submit_answers(_FakeSession(), {"q1": "x"})
        assert r["success"] is False

    def test_answer_length_capped(self):
        from l3.cell.peers.l3a.ask import ask_handler, submit_answers
        from l3.cell.peers.l3a.params import ASK_MAX_ANSWER_CHARS

        s = _FakeSession()
        ask_handler(s, {"questions": ["A?"]})
        submit_answers(s, {"q1": "x" * 99999})
        assert len(s._ask.questions[0].answer) == ASK_MAX_ANSWER_CHARS

    def test_answer_block_format(self):
        from l3.cell.peers.l3a.ask import AskState, build_answer_block

        st = AskState.from_questions(["Target platform?"])
        st.questions[0].answer = "windows"
        st.free_form = "also prefer CLI"
        block = build_answer_block(st)
        assert "User Clarification" in block
        assert "Target platform?" in block
        assert "windows" in block
        assert "CLI" in block


class TestSessionAskFlow:
    def _make_session(self):
        from l3.cell.peers.l3a.session import Session

        s = Session(session_id="l3a-flow", title="test")
        s._loop = _FakeLoop()
        return s

    def test_prompt_while_awaiting_routes_to_answer(self):
        from l3.cell.peers.l3a.ask import ask_handler

        s = self._make_session()
        ask_handler(s, {"questions": ["Platform?", "Language?"]})
        r = s.prompt("windows; python")
        assert r["success"] is True
        assert r["ask_resolved"] is True
        assert r["answer"] == "resumed-ok"
        assert s._ask.status == "answered"
        assert s._loop.runs == 1
        # Q&A block injected into history
        blocks = [m.content for m in s.history._messages if m.metadata.get("kind") == "ask_answer"]
        assert len(blocks) == 1
        assert "Platform?" in blocks[0]

    def test_resume_after_ask_no_answer_fails(self):
        from l3.cell.peers.l3a.ask import ask_handler

        s = self._make_session()
        ask_handler(s, {"questions": ["A?"]})
        r = s.resume_after_ask()
        assert r["success"] is False

    def test_submit_then_resume(self):
        from l3.cell.peers.l3a.ask import ask_handler

        s = self._make_session()
        ask_handler(s, {"questions": ["A?"]})
        s.submit_answers({"q1": "yes"}, "")
        r = s.resume_after_ask()
        assert r["success"] is True
        assert s._loop.runs == 1
        assert s._ask.status == "answered"

    def test_ask_status_api(self):
        from l3.cell.peers.l3a.ask import ask_handler

        s = self._make_session()
        assert s.ask_status()["status"] == "none"
        ask_handler(s, {"questions": ["A?"]})
        st = s.ask_status()
        assert st["status"] == "awaiting"
        assert st["ask"]["questions"][0]["question"] == "A?"

    def test_info_includes_ask(self):
        from l3.cell.peers.l3a.ask import ask_handler

        s = self._make_session()
        assert s.info()["ask"] is None
        ask_handler(s, {"questions": ["A?"]})
        assert s.info()["ask"]["status"] == "awaiting"


class TestApiDispatch:
    def _make_mgr(self):
        from l3.cell.peers.l3a.session import Session, SessionManager

        mgr = SessionManager()
        s = Session(session_id="l3a-dispatch", title="t")
        s._loop = _FakeLoop()
        with mgr._lock:
            mgr._sessions[s.id] = s
        return mgr, s

    def test_dispatch_ask_status(self):
        from l3.cell.peers.l3a import api
        from l3.cell.peers.l3a.ask import ask_handler

        mgr, s = self._make_mgr()
        ask_handler(s, {"questions": ["A?"]})
        r = api.dispatch(["ask", s.id], mgr, None, None)
        assert r["success"] is True
        assert r["ask"]["status"] == "awaiting"

    def test_dispatch_answer(self):
        from l3.cell.peers.l3a import api
        from l3.cell.peers.l3a.ask import ask_handler

        mgr, s = self._make_mgr()
        ask_handler(s, {"questions": ["A?"]})
        r = api.dispatch(["answer", s.id, "q1=hello"], mgr, None, None)
        assert r["success"] is True
        assert r["ask_resolved"] is True
        assert s._loop.runs == 1

    def test_dispatch_answer_unknown_session(self):
        from l3.cell.peers.l3a import api

        mgr, _ = self._make_mgr()
        r = api.dispatch(["answer", "nope", "q1=x"], mgr, None, None)
        assert r["success"] is False


class TestApiHandlersL3A:
    def test_handlers_importable(self):
        from l4.api_handlers.api_handlers_l3a import (
            handle_l3a_ask_answer,
            handle_l3a_ask_status,
        )

        assert callable(handle_l3a_ask_status)
        assert callable(handle_l3a_ask_answer)

    def test_status_requires_session(self):
        from l4.api_handlers.api_handlers_l3a import handle_l3a_ask_status

        r = handle_l3a_ask_status({})
        assert r["success"] is False

    def test_answer_requires_session(self):
        from l4.api_handlers.api_handlers_l3a import handle_l3a_ask_answer

        r = handle_l3a_ask_answer({"answers": {"q1": "x"}})
        assert r["success"] is False
