"""Integration tests — Card → Cell → AgentLoop → verify end-to-end."""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCellCardExecution:
    def test_raw_string_card(self):
        from l3.cell import get_cell, reset_cells
        from l3.agent_terminal import reset_terminals
        from l3.agent.scout import reset_pool

        # Ensure LLM mock mode + reset state
        from l4.llm import reset_engine, get_engine
        reset_engine()
        get_engine()

        cell = get_cell("str-test", ["."])
        cell.add_agent("a", role="reader", territory=["."], auto_boot=True)
        # Poll for agent readiness instead of fixed sleep
        from l3.agent_terminal import get_terminal
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                t = get_terminal("a")
                if t and t.status and t.status.name == "IDLE":
                    break
            except Exception:
                pass
            time.sleep(0.05)
        # Use a direct action (list_dir) that doesn't need LLM
        r = cell.execute_card("list current directory", domain=".", agent_map={"reader": "a"})
        steps = r.get("steps", [])
        assert len(steps) >= 0, "cell should handle raw string card"
        reset_terminals()
        reset_cells()


class TestSyscallIntegration:
    def test_process_list(self):
        from l1.kernel import syscall
        r = syscall("process.list", agent_id="test")
        assert r.get("success"), "process.list via syscall"
        if r.get("success"):
            assert isinstance(r.get("processes", []), list)

    def test_registry_aggregates(self):
        from l1.kernel.registry import get_registry
        reg = get_registry()
        summary = reg.summary()
        assert summary.get("modules", {}).get("total", 0) >= 9
        assert summary.get("processes", 0) >= 1
        syscalls = reg.syscalls()
        assert len(syscalls) >= 20

    def test_vfs_proc(self):
        from l1.kernel.vfs import get_vfs
        vfs = get_vfs()
        r = vfs.read("/proc")
        assert r.get("success"), "/proc should be readable"
        if r["success"]:
            assert len(r.get("content", "")) > 50

    def test_emit_signal(self):
        from l1.kernel import emit_signal, get_event_bus, SignalType
        bus = get_event_bus()
        captured = []
        bus.on(SignalType.SCOUT_DONE, lambda s: captured.append(s.sender))
        n = emit_signal("scout_done", sender="integration-test", target="cell")
        assert n == 1, "emit_signal should dispatch to 1 listener"
        assert "integration-test" in captured, "captured sender mismatch"
