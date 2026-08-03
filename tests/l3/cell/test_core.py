"""Cell Master Test — Init/Agent Management/Messages/Liveness/Emergency Stop/State Persistence"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCellInit:
    """Cell Initialization"""

    def test_basic_init(self):
        from l3.cell import Cell
        cell = Cell("test-cell-1", territory=["src", "docs"])
        assert cell.cell_id == "test-cell-1"
        assert "src" in cell.territory
        assert len(cell.territory) == 2

    def test_init_empty_territory(self):
        from l3.cell import Cell
        cell = Cell("empty-cell")
        assert cell.territory == []


class TestAddAgent:
    """Agent Addition"""

    def test_add_agent_basic(self):
        from l3.cell import Cell
        cell = Cell("cell-a")
        r = cell.add_agent("agent-1", role="reader", territory=["."],
                           ring=1, auto_boot=False)
        assert r["success"]

    def test_add_agent_duplicate(self):
        from l3.cell import Cell
        cell = Cell("cell-b")
        cell.add_agent("agent-x", role="reader")
        r = cell.add_agent("agent-x", role="writer")
        assert not r["success"]

    def test_add_agent_with_defaults(self):
        from l3.cell import Cell
        cell = Cell("cell-c")
        r = cell.add_agent("agent-y", role="reader")
        assert r["success"]

    def test_multiple_agents(self):
        from l3.cell import Cell
        cell = Cell("cell-d")
        cell.add_agent("a1", role="reader")
        cell.add_agent("a2", role="writer")
        cell.add_agent("a3", role="reviewer")
        assert len(cell._agents) == 3


class TestAgentStatus:
    """Agent Status"""

    def test_status_before_boot(self):
        from l3.cell import Cell
        cell = Cell("cell-s")
        cell.add_agent("agent-s1", role="reader")
        from l3.cell.components.cell_types import AgentStatus
        info = cell._agents.get("agent-s1")
        assert info is not None
        assert info.status == AgentStatus.IDLE


class TestLiveness:
    """Liveness Detection"""

    def test_liveness_empty_cell(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("live-cell")
        r = cell.liveness()
        assert r["cell_id"] == "live-cell"
        assert "overall" in r

    def test_liveness_with_agents(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("live-cell-2")
        cell.add_agent("live-a", role="reader")
        r = cell.liveness()
        assert r["total"] >= 1


class TestBootAndShutdown:
    """Boot/Shutdown"""

    def test_boot_all(self):
        from l3.agent_terminal import reset_terminals
        from l3.cell import Cell, reset_cells
        reset_cells()
        reset_terminals()
        cell = Cell("boot-cell")
        cell.add_agent("boot-a", role="reader")
        r = cell.boot_all()
        assert isinstance(r, dict)
        assert "agents" in r

    def test_shutdown_all(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("shutdown-cell")
        cell.add_agent("shut-a", role="reader")
        r = cell.shutdown_all()
        assert r["success"]

    def test_shutdown_empty(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("empty-shut")
        r = cell.shutdown_all()
        assert r["success"]


class TestEmergencyStop:
    """Emergency Stop"""

    def test_emergency_stop(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("emerg-cell")
        cell.add_agent("emerg-a", role="reader")
        r = cell.emergency_stop()
        assert r["success"]
        assert cell._emergency is True

    def test_resume(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("resume-cell")
        cell.add_agent("resume-a", role="reader")
        cell.emergency_stop()
        r = cell.resume()
        assert r["success"]
        assert cell._emergency is False

    def test_double_stop(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("dbl-stop")
        cell.emergency_stop()
        r2 = cell.emergency_stop()
        assert r2["success"]

    def test_execute_after_stop(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("stop-exec")
        cell.add_agent("exec-a", role="reader")
        cell.emergency_stop()
        r = cell.execute_card("list .", domain=".")
        assert not r["success"]
        assert "emergency" in r.get("error", "")


class TestMessaging:
    """Inter-Agent Messages"""

    def test_send_message_unknown_target(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("msg-cell")
        cell.add_agent("sender", role="reader")
        from l3.cell.components.cell_types import MessageType
        r = cell.send_message("sender", "unknown-target",
                              MessageType.CROSS_REVIEW_REQ)
        assert not r["success"]

    def test_send_message_unknown_sender(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("msg-cell-2")
        cell.add_agent("target", role="reader")
        from l3.cell.components.cell_types import MessageType
        r = cell.send_message("unknown-sender", "target",
                              MessageType.CROSS_REVIEW_REQ)
        assert not r["success"]

    def test_read_messages_empty(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("read-cell")
        cell.add_agent("reader-agent", role="reader")
        msgs = cell.read_messages("reader-agent")
        assert isinstance(msgs, list)


class TestStats:
    """Cell Statistics"""

    def test_stats_basic(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("stat-cell")
        s = cell.stats()
        assert s["cell_id"] == "stat-cell"
        assert "agents" in s

    def test_stats_with_agents(self):
        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("stat-cell-2")
        cell.add_agent("stat-a", role="reader")
        cell.add_agent("stat-b", role="writer")
        s = cell.stats()
        assert len(s["agents"]) == 2


class TestSaveRestoreState:
    """Cell State Save/Restore"""

    def test_save_state(self):
        import json
        import tempfile

        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("save-cell")
        cell.add_agent("save-a", role="reader")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            r = cell.save_state(path)
            assert r["success"]
            data = json.loads(open(path, encoding="utf-8").read())
            assert data["cell_id"] == "save-cell"
        finally:
            os.unlink(path)

    def test_restore_state(self):
        import json
        import tempfile

        from l3.cell import Cell, reset_cells
        reset_cells()
        cell = Cell("rest-cell")
        cell.add_agent("rest-a", role="reader")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"cell_id": "rest-cell", "agents": {}}, f)
            path = f.name
        try:
            r = cell.restore_state(path)
            assert r["success"]
        finally:
            os.unlink(path)
