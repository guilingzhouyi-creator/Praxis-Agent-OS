"""Tests for CellMonitor — Cell event ring buffer and status tracking."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_register_cell():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    r = cm.register_cell("cell-1", ["src"], {"agent-a": "reader"})
    assert r.get("success")
    cells = cm.list_cells()
    assert any(c["cell_id"] == "cell-1" for c in cells)


def test_get_cell():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    cm.register_cell("cell-2", ["docs"], {"agent-b": "writer"})
    cell = cm.get_cell("cell-2")
    assert cell is not None
    assert "docs" in cell.get("territory", [])


def test_get_events():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    cm.register_cell("cell-3", ["test"])
    events = cm.get_events(limit=10)
    assert len(events) >= 1
    assert events[0]["cell_id"] == "cell-3"


def test_report_agent():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    cm.register_cell("cell-4", ["app"])
    cm.report_agent("cell-4", "agent-x", role="reader", status="IDLE")
    cell = cm.get_cell("cell-4")
    assert cell is not None
    assert cell["agents"]["agent-x"]["role"] == "reader"


def test_report_crash():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    cm.register_cell("cell-5", ["data"])
    cm.report_agent_crash("cell-5", "agent-y", "OOM")
    events = cm.get_events(cell_id="cell-5")
    assert any(e["event"] == "crash" for e in events)


def test_report_card_result():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    cm.register_cell("cell-6", ["web"])
    cm.report_card_result("cell-6", "agent-z", "card-001", success=True)
    cm.report_card_result("cell-6", "agent-z", "card-002", success=False)
    events = cm.get_events(cell_id="cell-6")
    assert any(e["event"] == "card_done" for e in events)
    assert any(e["event"] == "card_fail" for e in events)


def test_stats():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    s = cm.stats()
    assert "cells" in s
    assert "events_total" in s


def test_unregister():
    from l3.cell.components.cell_monitor import CellMonitor
    cm = CellMonitor()
    cm.register_cell("cell-7", ["tmp"])
    cm.unregister_cell("cell-7")
    cells = cm.list_cells()
    assert not any(c["cell_id"] == "cell-7" for c in cells)


def test_get_module():
    from l3.cell.components.cell_monitor import get_cell_monitor, reset_cell_monitor
    reset_cell_monitor()
    m1 = get_cell_monitor()
    m2 = get_cell_monitor()
    assert m1 is m2
