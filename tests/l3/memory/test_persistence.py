"""Tests for persistence layer — versioning, PersistableMixin, round-trips."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from l1.kernel.versioning import check_and_migrate, stamp, register_migration
from l3._persistable import PersistableMixin


# ── Versioning tests ──

def test_stamp_adds_version():
    data = stamp({"foo": 1}, "snapshot")
    assert data["_version"] == 3  # SNAPSHOT_VERSION
    assert data["foo"] == 1


def test_check_and_migrate_current():
    data = stamp({"foo": 1}, "snapshot")
    result = check_and_migrate(data, "snapshot")
    assert result["foo"] == 1
    assert result["_version"] == 3


def test_check_and_migrate_too_new():
    data = {"_version": 999, "foo": 1}
    with pytest.raises(ValueError, match="too new|> current"):
        check_and_migrate(data, "snapshot")


def test_check_and_migrate_unknown_kind():
    data = {"_version": 1}
    result = check_and_migrate(data, "nonexistent")
    assert result == data  # passes through unchanged


def test_register_and_migrate():
    _called = []

    def _v1_to_v2(data):
        _called.append(1)
        data["migrated"] = True
        return data

    register_migration("snapshot", 1, "test", _v1_to_v2)
    data = {"_version": 1, "foo": 1}
    result = check_and_migrate(data, "snapshot")
    assert result["_version"] == 3  # migrated through 1→2→3
    assert result["migrated"] is True
    assert _called == [1]


# ── PersistableMixin tests ──

class _TestPersistable(PersistableMixin):
    persistence_kind = "card_registry"

    def __init__(self, path: str):
        self._data: dict = {}
        self._init_persistence(path, 0.0)
        self._restore()

    def _serialize(self) -> dict:
        return self._data

    def _deserialize(self, data: dict) -> bool:
        self._data = dict(data)
        return True


def test_persist_round_trip():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.json")
        obj = _TestPersistable(path)
        obj._data = {"hello": "world", "nested": {"a": 1}}
        result = obj._persist()
        assert result["success"] is True

        # Fresh object reads back — version field stored as part of serialized data
        obj2 = _TestPersistable(path)
        assert obj2._data.get("hello") == "world"
        assert obj2._data.get("_version") == 1  # version field stamped during _persist
        assert os.path.exists(path)


def test_persist_missing_file_returns_success_false():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "nonexistent.json")
        obj = _TestPersistable(path)
        result = obj._restore()
        assert result["success"] is False
        assert "no file" in result.get("error", "")


def test_persist_corrupted_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "bad.json")
        with open(path, "w") as f:
            f.write("{bad json}")
        obj = _TestPersistable(path)
        result = obj._restore()
        assert result["success"] is False


# ── CardRegistry persistence tests ──

from l3.card.card_registry import CardRegistry, get_registry, reset_registry


def test_card_registry_persist_round_trip():
    reset_registry()
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cards.json")
        reg = CardRegistry(persist_path=path)
        cid = reg.submit("test intent", domain="app", priority=3)
        reg.dispatch(cid, "cell-1")
        reg.complete(cid, {"ok": True})
        assert reg.get(cid) is not None
        reg.save()

        # New registry loads from same file
        reg2 = CardRegistry(persist_path=path)
        loaded = reg2.get(cid)
        assert loaded is not None, f"card {cid} not found in reloaded registry"
        assert loaded.summary.title == "test intent"
        assert loaded.state.value == "completed"
        assert loaded._completion_summary == "executed"

        stats = reg2.stats()
        assert stats["total"] == 1
    reset_registry()


def test_card_registry_persist_empty():
    reset_registry()
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cards_empty.json")
        reg = CardRegistry(persist_path=path)
        stats = reg.stats()
        assert stats["total"] == 0

        reg2 = CardRegistry(persist_path=path)
        stats2 = reg2.stats()
        assert stats2["total"] == 0
    reset_registry()


# ── TodoTable persistence tests ──

from l3.services.todo import TodoTable, TodoStatus


def test_todo_table_persist_round_trip():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "todos.json")
        tbl = TodoTable(agent_id="test-agent", persist_path=path)
        tid = tbl.add("task one", priority=1)
        tbl.update(tid, status=TodoStatus.DONE, result={"ok": True})
        assert tbl.get(tid) is not None
        tbl.save()

        tbl2 = TodoTable(agent_id="test-agent", persist_path=path)
        loaded = tbl2.get(tid)
        assert loaded is not None, f"todo {tid} not found in reloaded table"
        assert loaded.status.name == "DONE"


# ── TransactionArea persistence tests ──

from l3.card.transaction_area import get_service, reset_service


def test_transaction_area_persist_round_trip():
    reset_service()
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "tx.json")
        from l3.card.transaction_area import TransactionArea
        ta = TransactionArea(persist_path=path)
        result = ta.enqueue("test card", "app", size="small", auto_approve=True)
        assert result.get("status") == "approved"
        stats = ta.stats()
        assert stats["queue_size"] > 0
        ta._persist()

        ta2 = TransactionArea(persist_path=path)
        stats2 = ta2.stats()
        assert stats2["queue_size"] > 0


# ── ExecutionEngine persistence tests ──

from l3.card.execution_engine import ExecutionEngine, ExecutionPlan, Step


def test_execution_engine_persist_round_trip():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "exec.json")
        engine = ExecutionEngine(persist_path=path)

        def _mock_executor(tool, params, agent_id):
            return {"success": True, "data": "done"}

        plan = ExecutionPlan(plan_id="p-test", intent="test", agent_id="a1")
        plan.add_step("mock_tool", {"x": 1})
        result = engine.execute(plan, _mock_executor)
        assert result.success is True
        assert result.done == 1
        engine.save()

        # Verify reload
        engine2 = ExecutionEngine(persist_path=path)
        loaded = engine2.get_result("p-test")
        assert loaded is not None, "execution result not found after reload"
        assert loaded["success"] is True
        assert loaded["done"] == 1


# ── Statecharts snapshot tests ──

from l3.services.statecharts import AgentStatecharts


def test_statecharts_snapshot_round_trip():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "statecharts_agent.json")
        sc = AgentStatecharts(agent_id="s-agent", persist_path=path)
        # Dispatch some events to change state
        from l3.services.statecharts import EventType
        sc.dispatch(EventType.TASK_ASSIGN)
        assert sc.task.state != "IDLE"
        snap = sc.snapshot
        assert snap["Task"] != "IDLE"
        sc.save_snapshot()

        # New statecharts loads state
        sc2 = AgentStatecharts(agent_id="s-agent", persist_path=path)
        assert sc2.task.state == sc.task.state, f"expected {sc.task.state}, got {sc2.task.state}"
        assert sc2.snapshot == sc.snapshot


def test_statecharts_snapshot_no_file():
    sc = AgentStatecharts(agent_id="no-file")
    assert sc.task.state == "IDLE"


# ── DialogueSession persistence tests ──

from l3.card.dialogue_session import DialogueSession, SessionConfig


def test_dialogue_session_json_persist_round_trip():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "dialogue.json")
        cfg = SessionConfig()
        session = DialogueSession("d-agent", "test task", cfg, persist_path=path)
        session.start()
        session.record_turn("hello", "hi there", [{"name": "tool1", "args": {"a": 1}}])
        session.push_context("user", "more info")
        r = session._json_persist()
        assert r["success"] is True

        restored = DialogueSession.restore_from_json("d-agent", session.session_id, persist_path=path)
        assert restored is not None
        assert restored.task == "test task"
        assert len(restored._turns) == 1
        assert restored._turns[0].prompt == "hello"
        assert restored._turns[0].response == "hi there"
        assert restored.state.name == "WAITING"
        restored.complete()


def test_dialogue_session_json_persist_nonexistent():
    result = DialogueSession.restore_from_json("x", "nonexistent-session", "/tmp/nope.json")
    assert result is None


# ── Memory restore truncation tests ──

def test_memory_restore_limits_default_to_unlimited():
    from l1.kernel.params.system import MEMORY_RING2_RESTORE_LIMIT, MEMORY_RING3_RESTORE_LIMIT
    assert MEMORY_RING2_RESTORE_LIMIT == 0
    assert MEMORY_RING3_RESTORE_LIMIT == 0


# ── WAL mode test ──

def test_persist_wal_mode():
    from l1.kernel.persist import _get_db, clear
    db = _get_db()
    wal = db.execute("PRAGMA journal_mode").fetchone()[0]
    assert wal == "wal"
    clear()


# ── Configurable paths test ──

def test_params_persistence_paths():
    from l1.kernel.params.system import (
        CARD_REGISTRY_PATH,
        TODO_TABLE_PATH,
        TRANSACTION_AREA_PATH,
        STATECHARTS_PATH,
        EXECUTION_RESULTS_PATH,
        DIALOGUE_SESSION_PATH,
    )
    assert CARD_REGISTRY_PATH.endswith(".json")
    assert TODO_TABLE_PATH.endswith(".json")
    assert TRANSACTION_AREA_PATH.endswith(".json")
    assert STATECHARTS_PATH.endswith(".json")
    assert EXECUTION_RESULTS_PATH.endswith(".json")
    assert DIALOGUE_SESSION_PATH.endswith(".json")


# ── HTN Planner to_card tests ──

from l3.bus.htn_planner import get_service as get_htn, Task, TaskType


def test_htn_decompose_to_card():
    htn = get_htn()
    root = htn.decompose("Develop snake game", "app/game")
    assert root is not None
    assert len(root.sub_tasks) > 0

    card = htn.to_card(root)
    assert card is not None
    assert card.intent == "Develop snake game"
    assert len(card.phases) > 0
    for phase in card.phases:
        assert len(phase.steps) > 0


def test_htn_to_card_unknown_intent():
    htn = get_htn()
    root = htn.decompose("Do something random", "app/random")
    card = htn.to_card(root)
    assert card is not None
    assert len(card.phases) >= 1


def test_htn_to_card_phase_agents():
    htn = get_htn()
    root = htn.decompose("Fix crash in login", "app/fix")
    card = htn.to_card(root)
    agents = set()
    for phase in card.phases:
        for step in phase.steps:
            if step.agent:
                agents.add(step.agent)
    assert len(agents) > 0  # at least one agent role assigned


def test_htn_decompose_fallback_to_card_builder():
    from l3.card.card_builder import build_card
    card = build_card(
        task_id="test-fallback",
        intent="Do something completely random that won't match any pattern",
        domain="app",
    )
    assert card is not None
    assert card.intent
    assert len(card.phases) == 1  # default single-phase card


# ── IssueCard / IssueTable tests ──

from l3.card.issue import IssueCard, IssueItem, IssueStatus, IssueCardStatus, get_table, reset_table


def test_issue_card_create():
    card = IssueCard(title="Test Convention", intent="Discuss architecture")
    card.add_item("What DB to use?", "app/db", "l3", "agent-a")
    card.add_item("What API style?", "app/api", "l3", "agent-b")
    assert len(card.items) == 2
    assert card.status == IssueCardStatus.DRAFT


def test_issue_table_submit_and_get():
    reset_table()
    table = get_table()
    card = IssueCard(title="Test", intent="test")
    card.add_item("Q1", "app", "l3", "agent-a")
    table.submit(card)
    assert table.get(card.id) is not None
    assert len(table.list_by_status()) == 1


def test_issue_table_answer():
    reset_table()
    table = get_table()
    card = IssueCard(title="Test", intent="test")
    iid = card.add_item("Q1", "app", "l3", "agent-a")
    table.submit(card)
    ok = table.answer_item(card.id, iid, "Use PostgreSQL", "agent-a")
    assert ok
    item = None
    for it in card.items:
        if it.id == iid:
            item = it
            break
    assert item is not None
    assert item.status == IssueStatus.ANSWERED
    assert item.answer == "Use PostgreSQL"


def test_issue_table_supplement():
    reset_table()
    table = get_table()
    card = IssueCard(title="Test", intent="test")
    table.submit(card)
    iid = table.supplement(card.id, "New question", "app/extra", "agent-b")
    assert iid is not None
    assert len(card.items) == 1
    assert card.items[0].status == IssueStatus.SUPPLEMENTED


def test_issue_card_lifecycle():
    reset_table()
    table = get_table()
    card = IssueCard(title="Test", intent="test")
    card.add_item("Q1", "app", "l3", "agent-a")
    table.submit(card)
    assert card.status == IssueCardStatus.DRAFT
    table.set_status(card.id, IssueCardStatus.DELIBERATING)
    assert card.status == IssueCardStatus.DELIBERATING
    table.set_status(card.id, IssueCardStatus.CONVERGED)
    assert card.status == IssueCardStatus.CONVERGED
    assert card.converged_at > 0


def test_issue_table_summary():
    reset_table()
    table = get_table()
    c1 = IssueCard(title="A", intent="a")
    c1.add_item("Q1", "app", "l3", "agent-a")
    c2 = IssueCard(title="B", intent="b")
    c2.add_item("Q2", "app", "l3", "agent-b")
    table.submit(c1)
    table.submit(c2)
    s = table.summary()
    assert s["cards"] == 2
    assert s["total_items"] == 2


# ── CacheDocument tests ──

from l3.memory.cache_doc import get_store, reset_store


def test_cache_doc_put_and_get():
    reset_store()
    store = get_store()
    bid = store.put("Test Doc", "Hello world", tags=["test"])
    assert bid.startswith("cache-")
    doc = store.get(bid)
    assert doc is not None
    assert doc.title == "Test Doc"
    assert doc.content == "Hello world"


def test_cache_doc_get_content():
    reset_store()
    store = get_store()
    bid = store.put("Title", "Content here", tags=["a"])
    assert store.get_content(bid) == "Content here"
    assert store.get_content("nonexistent") == ""


def test_cache_doc_list_by_tag():
    reset_store()
    store = get_store()
    store.put("Doc1", "c1", tags=["alpha"])
    store.put("Doc2", "c2", tags=["beta"])
    store.put("Doc3", "c3", tags=["alpha", "beta"])
    alphas = store.list_by_tag("alpha")
    assert len(alphas) == 2
    betas = store.list_by_tag("beta")
    assert len(betas) == 2


def test_cache_doc_delete():
    reset_store()
    store = get_store()
    bid = store.put("To Delete", "bye")
    assert store.delete(bid) is True
    assert store.get(bid) is None


def test_cache_doc_stats():
    reset_store()
    store = get_store()
    store.put("A", "a", tags=["x"])
    store.put("B", "b", tags=["y"])
    stats = store.stats()
    assert stats["entries"] == 2
    assert stats["tags"] >= 1


# ── Convergence tests ──

from l3.agent.convergence import converge, to_execution_card
from l3.card.issue import IssueCard, IssueCardStatus


def test_converge_card_not_found():
    result = converge("nonexistent")
    assert result["success"] is False


def test_converge_card_not_converged():
    from l3.card.issue import get_table, reset_table
    reset_table()
    table = get_table()
    card = IssueCard(title="T", intent="t")
    card.add_item("Q", "app", "l3", "agent-a")
    table.submit(card)
    table.set_status(card.id, IssueCardStatus.DELIBERATING)
    result = converge(card.id)
    assert result["success"] is False


def test_converge_rule_based():
    from l3.card.issue import get_table, reset_table
    reset_table()
    table = get_table()
    card = IssueCard(title="Test", intent="test converge")
    card.add_item("Question 1", "app", "l3", "agent-a")
    card.add_item("Question 2", "app", "l3", "agent-b")
    table.submit(card)
    table.answer_item(card.id, card.items[0].id, "Answer 1", "agent-a")
    table.answer_item(card.id, card.items[1].id, "Answer 2", "agent-b")
    table.set_status(card.id, IssueCardStatus.CONVERGED)
    result = converge(card.id)
    assert result["success"] is True
    assert "summary" in result


def test_to_execution_card():
    card = IssueCard(title="Test", intent="test exec")
    card.add_item("Q1", "app", "l3", "agent-a")
    card.add_item("Q2", "app", "l3", "agent-b")
    card.items[0].answer = "A1"
    card.items[1].answer = "A2"
    exec_card = to_execution_card(card, '{"summary": "done"}')
    assert exec_card is not None
    assert exec_card.intent == "test exec"
    assert len(exec_card.phases) >= 1


# ── Cell convene integration tests ──

from l3.cell import Cell
from l3.card.issue import IssueCard, get_table, reset_table, IssueCardStatus


def test_cell_convene_starts_convention():
    reset_table()
    cell = Cell("test-cell", territory=["app"])
    cell.add_agent("agent-a", role="reader", territory=["app"], ring=1)
    cell.add_agent("agent-b", role="writer", territory=["app"], ring=1)

    card = IssueCard(title="Test Convention", intent="Discuss DB")
    card.add_item("Which DB?", "app", "l3", "")
    card.add_item("API style?", "app", "l3", "")
    table = get_table()
    table.submit(card)

    result = cell.convene(card)
    assert result["success"] is True
    assert result["card_id"] == card.id
    assert "agent-a" in result["participants"]
    assert "agent-b" in result["participants"]
    assert table.get(card.id).status == IssueCardStatus.DELIBERATING


def test_cell_execute_card_detects_issue_card():
    reset_table()
    cell = Cell("test-cell2")
    cell.add_agent("agent-a", role="reader", territory=[], ring=1)

    card = IssueCard(title="Test", intent="test")
    card.add_item("Q1", "", "l3", "")
    from l3.card.issue import get_table
    get_table().submit(card)

    # execute_card should route to convene() instead of normal execution
    result = cell.execute_card(card)
    assert result["success"] is True
    assert result["card_id"] == card.id


def test_cell_handle_convention_message():
    from l3.cell.components.cell_types import MessageType
    reset_table()
    cell = Cell("test-cell3")
    cell.add_agent("agent-a", role="reader", territory=["app"], ring=1)
    cell.add_agent("agent-b", role="writer", territory=["app"], ring=1)

    card = IssueCard(title="Test", intent="test")
    it = card.add_item("Q1", "app", "l3", "agent-b")
    from l3.card.issue import get_table
    get_table().submit(card)
    cell.convene(card)

    # Agent answers
    result = cell.handle_convention_message("agent-b", MessageType.REBUT, {
        "card_id": card.id, "statement": "I recommend PostgreSQL",
    })
    assert result["success"] is True


def test_cell_close_convention_full_flow():
    from l3.cell.components.cell_types import MessageType
    reset_table()
    from l3.memory.cache_doc import reset_store
    reset_store()
    cell = Cell("test-cell4")
    cell.add_agent("agent-a", role="reader", territory=["app"], ring=1)
    cell.add_agent("agent-b", role="writer", territory=["app"], ring=1)

    card = IssueCard(title="Test", intent="test flow")
    it1 = card.add_item("Which DB?", "app", "l3", "agent-b")
    it2 = card.add_item("API style?", "app", "l3", "agent-a")
    from l3.card.issue import get_table
    table = get_table()
    table.submit(card)
    cell.convene(card)

    # Agents answer
    cell.handle_convention_message("agent-b", MessageType.REBUT, {
        "card_id": card.id, "statement": "PostgreSQL",
    })
    table.answer_item(card.id, it1, "PostgreSQL", "agent-b")
    cell.handle_convention_message("agent-a", MessageType.REBUT, {
        "card_id": card.id, "statement": "REST",
    })
    table.answer_item(card.id, it2, "REST", "agent-a")

    # Close convention
    result = cell.close_convention(card.id)
    assert result["success"] is True
    assert result["issue_card_id"] == card.id
    assert "close" in result
    assert "convergence" in result


# ── Convention message dispatch to AgentTerminal tests ──

from l3.agent_terminal import AgentTerminal, TerminalCard, CardMode as TermCardMode


def test_convention_terminal_card_dispatched():
    from l3.cell.components.cell_types import MessageType
    """Cell.send_message creates a TerminalCard for convention messages."""
    reset_table()
    from l3.agent_terminal import reset_terminals
    reset_terminals()
    cell = Cell("test-cell-conv")
    cell.add_agent("agent-a", role="reader", territory=["app"], ring=1)
    cell.add_agent("cell-conv", role="writer", territory=["app"], ring=1)
    # Send via mailbox path only (simulate convention dispatch)
    result = cell.send_message("agent-a", "cell-conv",
                                MessageType.CONVENE,
                                {"card_id": "test-card", "title": "Test"})
    assert result["success"] is True


def test_agent_terminal_convention_unknown_msg():
    """Unknown convention message type returns error."""
    term = AgentTerminal("test-agent-conv", role="reader")
    card = TerminalCard(card_id="t1", action="convention",
                        target="unknown-card",
                        params={"msg_type": "UNKNOWN_TYPE", "payload": {}})
    result = term._convention_handler(card)
    assert result.success is False
    assert "unknown convention msg" in result.error


def test_agent_terminal_convention_start_no_card():
    """CONVENE with unknown card ID returns error."""
    term = AgentTerminal("test-agent-start", role="reader")
    card = TerminalCard(card_id="t2", action="convention",
                        target="nonexistent-card",
                        params={"msg_type": "CONVENE", "payload": {}})
    result = term._convention_handler(card)
    assert result.success is False
    assert "unknown convention" in result.error


def test_agent_terminal_convention_turn_no_session():
    """CROSS_EXAMINE without active session returns error."""
    term = AgentTerminal("test-agent-turn", role="reader")
    card = TerminalCard(card_id="t3", action="convention",
                        target="no-session-card",
                        params={"msg_type": "CROSS_EXAMINE",
                                "payload": {"statement": "Why?", "from": "agent-b"}})
    result = term._convention_handler(card)
    assert result.success is False
    assert "no active convention session" in result.error


def test_agent_terminal_convention_close_no_session():
    """CONVENE_CLOSE without active session is OK (cleanup)."""
    term = AgentTerminal("test-agent-close", role="reader")
    card = TerminalCard(card_id="t4", action="convention",
                        target="no-session-card",
                        params={"msg_type": "CONVENE_CLOSE", "payload": {}})
    result = term._convention_handler(card)
    assert result.success is True  # graceful cleanup


def test_agent_terminal_convention_propose():
    """PROPOSE_ISSUE handled even without active session."""
    term = AgentTerminal("test-agent-prop", role="reader")
    card = TerminalCard(card_id="t5", action="convention",
                        target="test-card",
                        params={"msg_type": "PROPOSE_ISSUE",
                                "payload": {"question": "Add testing?", "sender": "agent-b"}})
    result = term._convention_handler(card)
    assert result.success is True


def test_agent_terminal_process_card_routes_convention():
    """_process_card routes action='convention' to _convention_handler."""
    term = AgentTerminal("test-agent-route", role="reader")
    card = TerminalCard(card_id="t6", action="convention",
                        target="nonexistent",
                        params={"msg_type": "CONVENE", "payload": {}})
    result = term._process_card(card)
    assert result.success is False  # card not found, but correctly routed


def test_htn_planner_initialized_in_boot():
    """Verify HTN planner can be instantiated (as boot.py does)."""
    from l3.bus.htn_planner import get_service as get_htn
    htn = get_htn()
    stats = htn.stats()
    assert stats["methods"] >= 5  # All built-in methods registered
