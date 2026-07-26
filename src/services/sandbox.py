"""Sandbox — copy-on-write isolation for Agent file operations.

Model:
  Read:   from real project (read-only, shared)
  Write:  to sandbox (copy-on-write, per-Agent)
  Flush:  L3 approves → sandbox → real project
  Discard: sandbox deleted, project unchanged
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from kernel import get_rwlock
from kernel.params import SANDBOX_STATE_PATH, SANDBOX_STATE_AUTO_SAVE, SANDBOX_STATE_TEMPLATE

logger = logging.getLogger(__name__)

# Configurable sandbox root — cross-platform: falls back to OS temp dir
_DEFAULT_SANDBOX = os.path.join(tempfile.gettempdir(), "nomos-sandbox")
_SANDBOX_ROOT = os.environ.get("NOMOS_SANDBOX_ROOT", _DEFAULT_SANDBOX)


@dataclass
class SandboxEntry:
    path: str          # relative path in project
    sandbox_path: str  # absolute path in sandbox
    agent_id: str
    status: str = "pending"   # pending | staged | flushed | discarded
    original_hash: str = ""
    modified_at: float = field(default_factory=time.time)


class CellSandbox:
    """Sandbox for one Cell. Contains per-Agent write layers — persisted to JSON."""

    def __init__(self, cell_id: str, project_root: str, sandbox_root: str,
                 state_path: str = ""):
        self.cell_id = cell_id
        self.project_root = Path(project_root).resolve()
        self.sandbox_root = Path(sandbox_root).resolve() / cell_id
        self._agents: dict[str, Path] = {}
        self._entries: dict[str, SandboxEntry] = {}
        self._lock = threading.Lock()
        self._state_path = state_path or SANDBOX_STATE_PATH
        self._restore_state()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def _persist_state(self) -> None:
        try:
            data = {
                "_version": 1,
                "cell_id": self.cell_id,
                "agents": {aid: str(p) for aid, p in self._agents.items()},
                "entries": {eid: {
                    "path": e.path, "sandbox_path": e.sandbox_path,
                    "agent_id": e.agent_id, "status": e.status,
                    "original_hash": e.original_hash, "modified_at": e.modified_at,
                } for eid, e in self._entries.items()},
            }
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, self._state_path)
        except Exception as e:
            logger.warning("sandbox persist failed: %s", e)

    def _restore_state(self) -> None:
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            for aid, path_str in data.get("agents", {}).items():
                self._agents[aid] = Path(path_str)
            for eid, ed in data.get("entries", {}).items():
                self._entries[eid] = SandboxEntry(
                    path=ed["path"], sandbox_path=ed["sandbox_path"],
                    agent_id=ed["agent_id"], status=ed.get("status", "pending"),
                    original_hash=ed.get("original_hash", ""),
                    modified_at=ed.get("modified_at", 0.0),
                )
            logger.info("sandbox restored: %d agents, %d entries",
                        len(self._agents), len(self._entries))
        except Exception as e:
            logger.warning("sandbox restore failed: %s", e)

    def register_agent(self, agent_id: str) -> Path:
        """Create a sandbox subdirectory for an agent."""
        agent_dir = self.sandbox_root / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._agents[agent_id] = agent_dir
            self._persist_state()
        return agent_dir

    def read(self, rel_path: str, agent_id: str) -> dict:
        """Read a file: sandbox first, then project."""
        safe_rel = self._sanitize_rel_path(rel_path)
        if safe_rel is None:
            return {"success": False, "error": f"invalid rel_path: {rel_path!r}"}
        sandbox_file = self._agent_path(agent_id) / safe_rel
        if sandbox_file.exists():
            try:
                content = sandbox_file.read_text(encoding="utf-8")
                return {"success": True, "content": content, "source": "sandbox", "path": str(sandbox_file)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        real_file = self.project_root / safe_rel
        if real_file.exists():
            try:
                content = real_file.read_text(encoding="utf-8")
                return {"success": True, "content": content, "source": "project", "path": str(real_file)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "file not found"}

    def write(self, rel_path: str, content: str, agent_id: str) -> dict:
        """Write to sandbox (copy-on-write from project)."""
        safe_rel = self._sanitize_rel_path(rel_path)
        if safe_rel is None:
            return {"success": False, "error": f"invalid rel_path: {rel_path!r}"}
        lock_name = f"sandbox:{self.cell_id}:{safe_rel}"
        rw = get_rwlock(lock_name)
        r = rw.write_lock(agent_id)
        if not r["success"]:
            return {"success": False, "error": "lock failed"}

        try:
            target = self._agent_path(agent_id) / safe_rel
            # Defensive check: resolved target must remain inside sandbox_root
            try:
                target.resolve().relative_to(self.sandbox_root.resolve())
            except ValueError:
                return {"success": False, "error": "target escapes sandbox root"}
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

            entry = SandboxEntry(
                path=safe_rel, sandbox_path=str(target),
                agent_id=agent_id, status="pending",
            )
            with self._lock:
                self._entries[safe_rel] = entry
                self._persist_state()

            return {"success": True, "sandbox_path": str(target), "source": "sandbox"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            rw.unlock(agent_id)

    def stage(self, agent_id: str) -> dict:
        """Stage all pending changes for L3 review."""
        staged = []
        with self._lock:
            for rel_path, entry in self._entries.items():
                if entry.agent_id == agent_id and entry.status == "pending":
                    entry.status = "staged"
                    staged.append(rel_path)
            self._persist_state()
        return {"success": True, "staged": staged, "count": len(staged)}

    def flush(self, agent_id: str, rel_paths: list[str] | None = None) -> dict:
        """Flush approved sandbox changes to the real project."""
        flushed = []
        with self._lock:
            targets = [(p, e) for p, e in self._entries.items()
                       if e.agent_id == agent_id and e.status == "staged"
                       and (rel_paths is None or p in rel_paths)]

        for rel_path, entry in targets:
            src = Path(entry.sandbox_path)
            dst = self.project_root / rel_path
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                entry.status = "flushed"
                flushed.append(rel_path)
            except Exception as e:
                logger.error("flush failed: %s: %s", rel_path, e)

        with self._lock:
            self._persist_state()
        return {"success": True, "flushed": flushed, "count": len(flushed)}

    def discard(self, agent_id: str = "") -> dict:
        """Discard sandbox changes."""
        agent_dir = self._agent_path(agent_id) if agent_id else self.sandbox_root
        count = 0
        with self._lock:
            to_discard = [(p, e) for p, e in self._entries.items()
                          if (not agent_id or e.agent_id == agent_id)]
            for rel_path, entry in to_discard:
                if entry.status in ("pending", "staged"):
                    entry.status = "discarded"
                    count += 1
            self._persist_state()

        try:
            if agent_dir.exists():
                shutil.rmtree(str(agent_dir))
                if agent_id:
                    self.register_agent(agent_id)
        except Exception as e:
            return {"success": True, "discarded": count, "warning": str(e)}

        return {"success": True, "discarded": count}

    def status(self) -> dict:
        with self._lock:
            pending = sum(1 for e in self._entries.values() if e.status == "pending")
            staged = sum(1 for e in self._entries.values() if e.status == "staged")
            flushed = sum(1 for e in self._entries.values() if e.status == "flushed")
            return {
                "cell_id": self.cell_id,
                "agents": list(self._agents.keys()),
                "entries": len(self._entries),
                "pending": pending, "staged": staged, "flushed": flushed,
            }

    def _agent_path(self, agent_id: str) -> Path:
        with self._lock:
            return self._agents.get(agent_id, self.sandbox_root / agent_id)

    def _sanitize_rel_path(self, rel_path: str) -> str | None:
        """Reject ``rel_path`` values that escape the sandbox/project root.

        Path traversal (``..`` segments, absolute paths) would let an agent
        read or overwrite files outside its territory, so we normalize the
        path and refuse anything that resolves to a parent directory.
        Returns the cleaned relative path as a POSIX-style string, or
        ``None`` if the input is unsafe.
        """
        if not rel_path or rel_path is None:
            return None
        # Reject absolute paths outright
        p = Path(rel_path)
        if p.is_absolute():
            return None
        # Normalize and re-check for .. escaping the root
        try:
            normalized = (self.project_root / p).resolve()
            normalized.relative_to(self.project_root.resolve())
        except ValueError:
            return None
        # Return a POSIX-style relative path
        return p.as_posix()


class SandboxManager:
    """Manages sandboxes for all Cells."""

    def __init__(self, sandbox_root: str | None = None):
        self._sandbox_root = Path(sandbox_root or _SANDBOX_ROOT).resolve()
        self._cells: dict[str, CellSandbox] = {}
        self._lock = threading.Lock()

    def create_cell(self, cell_id: str, project_root: str) -> dict:
        with self._lock:
            if cell_id in self._cells:
                return {"success": False, "error": "cell already exists"}
            # Give each cell its own state file so cells don't load
            # each other's entries via the shared SANDBOX_STATE_PATH.
            state_path = str(self._sandbox_root / SANDBOX_STATE_TEMPLATE.format(cell_id=cell_id))
            sb = CellSandbox(cell_id, project_root, str(self._sandbox_root),
                             state_path=state_path)
            self._cells[cell_id] = sb
            return {"success": True, "cell_id": cell_id, "sandbox_root": str(sb.sandbox_root)}

    def get_cell(self, cell_id: str) -> CellSandbox | None:
        with self._lock:
            return self._cells.get(cell_id)

    def register_agent(self, cell_id: str, agent_id: str) -> dict:
        sb = self.get_cell(cell_id)
        if not sb:
            return {"success": False, "error": "cell not found"}
        sb.register_agent(agent_id)
        return {"success": True, "agent_id": agent_id, "cell_id": cell_id}

    def status(self) -> dict:
        with self._lock:
            return {cid: sb.status() for cid, sb in self._cells.items()}

    def cleanup(self, cell_id: str = "") -> dict:
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


def get_manager(sandbox_root: str | None = None) -> SandboxManager:
    global _manager
    if _manager is None:
        _manager = SandboxManager(sandbox_root)
    return _manager


def reset_manager() -> None:
    global _manager
    if _manager:
        _manager.cleanup()
    _manager = None
