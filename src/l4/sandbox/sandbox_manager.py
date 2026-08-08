"""Sandbox manager + root resolution — extracted from cell_sandbox.py.

``SandboxManager`` owns the per-Cell ``CellSandbox`` instances; the module
also carries the configurable sandbox root (env-overridable) and the manager
singleton helpers.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from l1.kernel.params.api import ENV_SANDBOX_ROOT
from l1.kernel.params.system import SANDBOX_STATE_TEMPLATE
from l1.kernel.platform import get_temp_dir as _get_temp_dir

if TYPE_CHECKING:
    from .cell_sandbox import CellSandbox

logger = logging.getLogger(__name__)

# ── Sandbox timing constants ──

# Configurable sandbox root — cross-platform: falls back to OS temp dir
_DEFAULT_SANDBOX = os.path.join(_get_temp_dir(), "praxis-sandbox")
_SANDBOX_ROOT = os.environ.get(ENV_SANDBOX_ROOT, _DEFAULT_SANDBOX)


class SandboxManager:
    """Manages sandboxes for all Cells."""

    def __init__(self, sandbox_root: str | None = None):
        self._sandbox_root = Path(sandbox_root or _SANDBOX_ROOT).resolve()
        self._cells: dict[str, CellSandbox] = {}
        self._lock = threading.Lock()

    def create_cell(self, cell_id: str, project_root: str) -> dict:
        """Create a new CellSandbox instance for the given cell id and project root."""
        from .cell_sandbox import CellSandbox

        with self._lock:
            if cell_id in self._cells:
                return {"success": False, "error": "cell already exists"}
            # Give each cell its own state file so cells don't load
            # each other's entries via the shared sandbox_state path.
            state_path = str(self._sandbox_root / SANDBOX_STATE_TEMPLATE.format(cell_id=cell_id))
            sb = CellSandbox(cell_id, project_root, str(self._sandbox_root), state_path=state_path)
            self._cells[cell_id] = sb
            return {"success": True, "cell_id": cell_id, "sandbox_root": str(sb.sandbox_root)}

    def get_cell(self, cell_id: str) -> CellSandbox | None:
        """Get the sandbox for a cell by ID."""
        with self._lock:
            return self._cells.get(cell_id)

    def register_agent(self, cell_id: str, agent_id: str) -> dict:
        """Register an agent under a cell's sandbox."""
        sb = self.get_cell(cell_id)
        if not sb:
            return {"success": False, "error": "cell not found"}
        sb.register_agent(agent_id)
        return {"success": True, "agent_id": agent_id, "cell_id": cell_id}

    def status(self) -> dict:
        """Return overall sandbox manager status."""
        with self._lock:
            return {cid: sb.status() for cid, sb in self._cells.items()}

    def cleanup(self, cell_id: str = "") -> dict:
        """Clean up stale sandbox directories."""
        with self._lock:
            if cell_id:
                sb = self._cells.pop(cell_id, None)
                if sb:
                    shutil.rmtree(str(sb.sandbox_root), ignore_errors=True)
                    return {"success": True}
                return {"success": False, "error": "cell not found"}
            count = len(self._cells)
            for sb in self._cells.values():
                shutil.rmtree(str(sb.sandbox_root), ignore_errors=True)
            self._cells.clear()
            return {"success": True, "cleaned": count}


_manager: SandboxManager | None = None
_manager_lock = threading.Lock()


def get_manager(sandbox_root: str | None = None) -> SandboxManager:
    """Get the sandbox manager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SandboxManager(sandbox_root)
    return _manager


def reset_manager() -> None:
    """Reset the singleton SandboxManager (for testing)."""
    global _manager
    if _manager:
        _manager.cleanup()
    _manager = None
