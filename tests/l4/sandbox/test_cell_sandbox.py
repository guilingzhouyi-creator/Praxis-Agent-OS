"""CellSandbox — sandbox entry management, diff, status tests."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCellSandbox:
    """CellSandbox — per-Cell sandbox with staged file changes."""

    def test_create_sandbox(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox(cell_id="test-cell", project_root=td, sandbox_root=td)
            assert sb.cell_id == "test-cell"

    def test_register_agent(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox(cell_id="test-cell", project_root=td, sandbox_root=td)
            sb.register_agent("agent-a")

    def test_status(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox(cell_id="stat-cell", project_root=td, sandbox_root=td)
            st = sb.status()
            assert isinstance(st, dict)

    def test_get_entries(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox(cell_id="entries-cell", project_root=td, sandbox_root=td)
            entries = sb.get_entries()
            assert isinstance(entries, list)
