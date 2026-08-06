"""AutoTestGate tests — mode switch, feedback queue, card attachment, API/L2."""

from __future__ import annotations

import time

import pytest

from l3.tool_system.auto_test import (
    auto_test_status,
    clear_feedback,
    get_auto_test_mode,
    maybe_trigger,
    parse_pytest_failures,
    pending_feedback,
    pop_feedback,
    push_feedback,
    reset_auto_test,
    set_auto_test,
)


@pytest.fixture(autouse=True)
def _reset_at():
    reset_auto_test()
    clear_feedback()
    yield
    reset_auto_test()
    clear_feedback()


class TestModeSwitch:
    def test_default_is_off(self):
        assert get_auto_test_mode() == "off"

    def test_set_valid_modes(self):
        assert set_auto_test("async")["success"]
        assert get_auto_test_mode() == "async"
        assert set_auto_test("off")["success"]
        assert get_auto_test_mode() == "off"

    def test_set_invalid_mode_rejected(self):
        r = set_auto_test("gate")
        assert not r["success"] and "invalid" in r["error"]

    def test_reset_returns_to_config(self):
        set_auto_test("async", source="api")
        r = reset_auto_test()
        assert r["success"] and r["mode"] == "off"

    def test_status_reports_pending(self):
        set_auto_test("async")
        push_feedback("writer", {"passed": False, "failures": ["x"]})
        st = auto_test_status()
        assert st["mode"] == "async"
        assert st["pending_feedback"] == 1
        assert st["pending_by_agent"].get("writer") == 1


class TestFeedbackQueue:
    def test_push_pop_exact_agent(self):
        push_feedback("writer", {"passed": False})
        push_feedback("reader", {"passed": True})
        popped = pop_feedback("writer")
        assert len(popped) == 1 and popped[0]["agent_id"] == "writer"
        assert len(pending_feedback()) == 1

    def test_pop_oldest_global(self):
        push_feedback("writer", {"seq": 1})
        push_feedback("writer", {"seq": 2})
        popped = pop_feedback("")
        assert len(popped) == 1 and popped[0]["seq"] == 1

    def test_pop_empty(self):
        assert pop_feedback("nobody") == []
        assert pop_feedback("") == []


class TestParseFailures:
    def test_parses_failed_and_error_lines(self):
        out = (
            "FAILED tests/a.py::test_one - AssertionError: boom\n"
            "FAILED tests/b.py::test_two - TypeError\n"
            "ERROR tests/c.py::test_three - ImportError\n"
            "4 failed, 12 passed in 0.42s\n"
        )
        failures = parse_pytest_failures(out)
        assert failures == [
            "tests/a.py::test_one",
            "tests/b.py::test_two",
            "tests/c.py::test_three",
        ]

    def test_empty_output(self):
        assert parse_pytest_failures("12 passed in 0.30s") == []
        assert parse_pytest_failures("") == []

    def test_dedup_and_cap(self):
        out = "FAILED t::a - x\nFAILED t::a - y\n"
        assert parse_pytest_failures(out) == ["t::a"]


class TestTrigger:
    def test_off_mode_no_trigger(self):
        assert get_auto_test_mode() == "off"
        assert maybe_trigger("writer", "cell1", "task", ["a.py"]) is False

    def test_async_no_edits_no_trigger(self):
        set_auto_test("async")
        assert maybe_trigger("writer", "cell1", "task", []) is False

    def test_async_spawns_background_run(self, monkeypatch):
        set_auto_test("async")
        calls = []

        def fake_execute():
            calls.append(1)
            return {"passed": False, "command": "pytest",
                    "failures": ["tests/x.py::test_bad"], "output": "FAILED tests/x.py::test_bad"}

        monkeypatch.setattr("l3.tool_system.auto_test._execute_tests", fake_execute)
        spawned = maybe_trigger("writer", "", "fix the bug", ["src/a.py"])
        assert spawned is True
        deadline = time.time() + 3.0
        while time.time() < deadline and not pending_feedback():
            time.sleep(0.05)
        assert calls, "background run never executed"
        fb = pending_feedback()
        assert fb and fb[0]["agent_id"] == "writer"
        assert fb[0]["passed"] is False
        assert fb[0]["failures"] == ["tests/x.py::test_bad"]


class TestCardwriteAttachment:
    def test_cardwrite_consumes_feedback_and_prioritizes(self):
        from l3.card.card_registry import get_registry, reset_registry
        from l3.cell.peers.l3a.helpers import cardwrite_handler

        reset_registry()
        push_feedback("writer", {"passed": False,
                                 "failures": ["tests/x.py::test_bad"]})
        r = cardwrite_handler({"title": "fix failing test", "priority": 5},
                              agent_id="writer")
        assert r["success"]
        reg = get_registry()
        card = reg._cards.get(r["card_id"])
        assert card is not None
        assert card.priority == 1  # promoted to highest priority
        fb = card.summary.columns.get("_test_feedback")
        assert fb and fb[0]["agent_id"] == "writer"
        reset_registry()

    def test_cardwrite_without_feedback_keeps_priority(self):
        from l3.card.card_registry import get_registry, reset_registry
        from l3.cell.peers.l3a.helpers import cardwrite_handler

        reset_registry()
        r = cardwrite_handler({"title": "normal card", "priority": 5})
        assert r["success"]
        card = get_registry()._cards.get(r["card_id"])
        assert card.priority == 5
        assert "_test_feedback" not in card.summary.columns
        reset_registry()


class TestApiAndShell:
    def test_api_get_set(self):
        from l4.api_handlers import ApiHandlers

        api = ApiHandlers()
        r = api._loop_auto_test_get()
        assert r["success"] and r["mode"] == "off"
        r = api._loop_auto_test_set({"mode": "async"})
        assert r["success"] and r["mode"] == "async"
        r = api._loop_auto_test_set({"mode": "bogus"})
        assert not r["success"]

    def test_shell_command(self):
        from l2.l2_shell.commands.test_auto import _cmd_test_auto

        r = _cmd_test_auto([])
        assert r["success"] and "mode" in r
        r = _cmd_test_auto(["async"])
        assert r["success"] and r["mode"] == "async"
        r = _cmd_test_auto(["reset"])
        assert r["success"]
        r = _cmd_test_auto(["nope"])
        assert not r["success"]


class TestCadenceHook:
    def test_unverified_edits_public_api(self):
        from l3.agent.verify_cadence import VerifyCadence

        vc = VerifyCadence()
        vc.record_edit("src/a.py")
        assert vc.unverified_edits() == ["src/a.py"]
        vc.record_check("pytest")
        assert vc.unverified_edits() == []
