"""Sandbox — copy-on-write isolation for Agent file operations.

Model:
  Read:   from real project (read-only, shared)
  Write:  to sandbox (copy-on-write, per-Agent)
  Flush:  L3 approves → sandbox → real project
  Discard: sandbox deleted, project unchanged

The per-file change record (``SandboxEntry``) + diff color scheme live in
``sandbox_entry.py``; the multi-Cell ``SandboxManager`` + singleton in
``sandbox_manager.py``. This module keeps ``CellSandbox`` (the per-Cell store)
and re-exports the other pieces so existing import paths keep working.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from l1.kernel import get_rwlock
from l1.kernel.params.system import HASH_TRUNC_LONG
from l1.kernel.paths import get_paths as _gp

from .sandbox_diff import check_conflict, compute_hunks
from .sandbox_entry import (  # noqa: F401 — re-export
    SandboxEntry,
    get_color_scheme,
    reset_color_scheme,
    set_color_scheme,
)
from .sandbox_manager import (  # noqa: F401 — re-export
    SandboxManager,
    get_manager,
    reset_manager,
)

logger = logging.getLogger(__name__)


class CellSandbox:
    """Sandbox for one Cell. Contains per-Agent write layers — persisted to JSON."""

    def __init__(self, cell_id: str, project_root: str, sandbox_root: str, state_path: str = ""):
        self.cell_id = cell_id
        self.project_root = Path(project_root).resolve()
        self.sandbox_root = Path(sandbox_root).resolve() / cell_id
        self._agents: dict[str, Path] = {}
        self._entries: dict[str, SandboxEntry] = {}
        self._path_index: dict[str, list[str]] = {}  # rel_path → [entry_key, ...]
        self._lock = threading.Lock()
        self._state_path = state_path or _gp().sandbox_state
        self._summary_cache: dict[str, dict] = {}  # path → summary (L2, shared across requests)
        self._restore_state()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def _persist_state(self) -> None:
        try:
            data = {
                "_version": 3,
                "cell_id": self.cell_id,
                "agents": {aid: str(p) for aid, p in self._agents.items()},
                "entries": {eid: e.to_serializable() for eid, e in self._entries.items()},
                "summary_cache": dict(self._summary_cache),
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
                self._entries[eid] = SandboxEntry.from_dict(ed)
                rel_path = ed.get("path", "")
                if rel_path:
                    self._path_index.setdefault(rel_path, []).append(eid)
            self._summary_cache.update(data.get("summary_cache", {}))
            logger.info("sandbox restored: %d agents, %d entries", len(self._agents), len(self._entries))
        except Exception as e:
            logger.warning("sandbox restore failed: %s", e)

    def register_agent(self, agent_id: str) -> Path:
        """Create and return the agent's private sandbox directory."""
        agent_dir = self.sandbox_root / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._agents[agent_id] = agent_dir
            self._persist_state()
        return agent_dir

    def _get_old_content(self, rel_path: str, agent_id: str, depends_on: list[str] | None = None) -> tuple[str, str]:
        """Get the "old" content for diff purposes.

        Resolution order:
          1. If ``depends_on`` is set, try upstream agents' sandbox copies first.
          2. Fall back to own sandbox checkpoint (last committed via flush).
          3. Fall back to project base file.
          4. Empty string for new files.

        Returns (content, source) where source is one of:
          "upstream", "checkpoint", "project", "empty".
        """
        safe_rel = self._sanitize_rel_path(rel_path) or rel_path

        # 1. Upstream agents (task dependency chain)
        if depends_on:
            for upstream_id in depends_on:
                up_path = self._agent_path(upstream_id) / safe_rel
                if up_path.exists():
                    try:
                        return up_path.read_text(encoding="utf-8"), "upstream"
                    except Exception:
                        logger.warning("sandbox: upstream read failed for %s", up_path)
                        continue

        # 2. Own checkpoint (last flushed)
        sb_path = self._agent_path(agent_id) / safe_rel
        if sb_path.exists():
            try:
                return sb_path.read_text(encoding="utf-8"), "checkpoint"
            except Exception:
                logger.warning("sandbox: checkpoint read failed for %s", sb_path)

        # 3. Project base
        real_file = self.project_root / safe_rel
        if real_file.exists():
            try:
                return real_file.read_text(encoding="utf-8"), "project"
            except Exception:
                logger.warning("sandbox: project read failed for %s", real_file)

        # 4. New file
        return "", "empty"

    def read(self, rel_path: str, agent_id: str, depends_on: list[str] | None = None) -> dict:
        """Read a file with cross-agent version routing.

        Resolution order:
          1. Own sandbox copy (fastest path)
          2. Upstream agent's sandbox (if depends_on chain leads there)
          3. Project base file
          4. Not found

        ``depends_on`` is the HTN task dependency chain — when set,
        the read will prefer upstream agents' pending content over
        the project base, so the agent sees the latest collaborative state.
        """
        safe_rel = self._sanitize_rel_path(rel_path)
        if safe_rel is None:
            return {"success": False, "error": f"invalid rel_path: {rel_path!r}"}

        # 1. Own sandbox (agent's own pending edits)
        sandbox_file = self._agent_path(agent_id) / safe_rel
        if sandbox_file.exists():
            try:
                content = sandbox_file.read_text(encoding="utf-8")
                return {
                    "success": True,
                    "content": content,
                    "source": "sandbox",
                    "path": str(sandbox_file),
                    "agent_id": agent_id,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        # 2. Upstream agents via task dependency chain
        if depends_on:
            for upstream_id in depends_on:
                if upstream_id == agent_id:
                    continue
                up_file = self._agent_path(upstream_id) / safe_rel
                if up_file.exists():
                    try:
                        content = up_file.read_text(encoding="utf-8")
                        return {
                            "success": True,
                            "content": content,
                            "source": "upstream",
                            "path": str(up_file),
                            "agent_id": upstream_id,
                        }
                    except Exception as e:
                        return {"success": False, "error": str(e)}

        # 3. Project base
        real_file = self.project_root / safe_rel
        if real_file.exists():
            try:
                content = real_file.read_text(encoding="utf-8")
                return {"success": True, "content": content, "source": "project", "path": str(real_file)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "file not found"}

    def write(
        self,
        rel_path: str,
        content: str,
        agent_id: str,
        task_id: str = "",
        tool_name: str = "",
        depends_on: list[str] | None = None,
    ) -> dict:
        """Write to sandbox with structured diff, conflict detection, and event broadcast.

        Args:
            rel_path: Relative file path in project.
            content: New file content.
            agent_id: Writing agent's ID.
            task_id: HTN task ID that triggered this write (for dependency routing).
            depends_on: List of upstream agent/task IDs this write depends on.

        Returns:
            Dict with ``success``, ``sandbox_path``, ``entry`` (full SandboxEntry),
            and optional ``conflict`` details.
        """
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
            try:
                target.resolve().relative_to(self.sandbox_root.resolve())
            except ValueError:
                return {"success": False, "error": "target escapes sandbox root"}

            # 1. Get old content for diff
            old_content, old_source = self._get_old_content(rel_path, agent_id, depends_on)

            # 2. Compute structured diff with agent/tool attribution
            now = time.time()
            hunks = compute_hunks(old_content, content, agent_id=agent_id, tool_name=tool_name, timestamp=now)
            additions = sum(len(h["added_lines"]) for h in hunks)
            deletions = sum(len(h["removed_lines"]) for h in hunks)
            stats = {"additions": additions, "deletions": deletions, "hunks": len(hunks)}

            # 3. Conflict detection (other agents' pending entries)
            with self._lock:
                conflict = check_conflict(safe_rel, agent_id, self._path_index, self._entries)

            # 4. Write to sandbox disk
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

            # 5. Build entry with full metadata
            old_hash = hashlib.sha256(old_content.encode("utf-8")).hexdigest()[:HASH_TRUNC_LONG] if old_content else ""
            entry = SandboxEntry(
                path=safe_rel,
                sandbox_path=str(target),
                agent_id=agent_id,
                tool_name=tool_name,
                status="pending",
                original_hash=old_hash,
                hunks=hunks,
                stats=stats,
                task_id=task_id,
                depends_on=list(depends_on or []),
                conflict_level=conflict,
            )
            with self._lock:
                self._entries[f"{safe_rel}::{agent_id}"] = entry
                self._path_index.setdefault(safe_rel, []).append(f"{safe_rel}::{agent_id}")
                self._summary_cache.pop(safe_rel, None)  # invalidate L2
                self._persist_state()

            # 6. Emit FILE_CHANGED event via EventBus
            try:
                from l1.kernel.event import Signal, SignalType
                from l1.kernel.event import get_bus as _get_ebus

                ebus = _get_ebus()
                ebus.emit(
                    Signal(
                        type=SignalType.FILE_CHANGED,
                        sender=f"sandbox:{self.cell_id}",
                        target=agent_id,
                        data={
                            "path": safe_rel,
                            "agent_id": agent_id,
                            "tool_name": tool_name,
                            "cell_id": self.cell_id,
                            "task_id": task_id,
                            "stats": stats,
                            "conflict_level": conflict,
                            "old_source": old_source,
                            "hunks_count": len(hunks),
                        },
                    )
                )
            except Exception:
                logger.debug("sandbox: FILE_CHANGED emit failed")

            return {
                "success": True,
                "sandbox_path": str(target),
                "source": "sandbox",
                "entry": entry.to_serializable(),
                "conflict": conflict,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            rw.unlock(agent_id)

    def stage(self, agent_id: str) -> dict:
        """Mark all pending entries of an agent as staged."""
        staged = []
        with self._lock:
            for _key, entry in self._entries.items():
                if entry.agent_id == agent_id and entry.status == "pending":
                    entry.status = "staged"
                    staged.append(entry.path)
            self._persist_state()
        return {"success": True, "staged": staged, "count": len(staged)}

    def flush(self, agent_id: str, rel_paths: list[str] | None = None) -> dict:
        """Flush approved sandbox changes to the real project."""
        flushed = []
        with self._lock:
            targets = [
                (entry, entry.path)
                for entry in self._entries.values()
                if entry.agent_id == agent_id
                and entry.status == "staged"
                and (rel_paths is None or entry.path in rel_paths)
            ]

        for entry, rel_path in targets:
            src = Path(entry.sandbox_path)
            dst = self.project_root / rel_path
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                entry.status = "flushed"
                flushed.append(rel_path)
                # Clean up path_index for flushed entries
                if rel_path in self._path_index:
                    entry_key = f"{rel_path}::{agent_id}"
                    try:
                        self._path_index[rel_path].remove(entry_key)
                        if not self._path_index[rel_path]:
                            del self._path_index[rel_path]
                    except ValueError:
                        logger.debug("cell_sandbox: path index entry already removed, skipping")
            except Exception as e:
                logger.error("flush failed: %s: %s", rel_path, e)

        with self._lock:
            self._persist_state()
        return {"success": True, "flushed": flushed, "count": len(flushed)}

    def discard(self, agent_id: str = "") -> dict:
        """Discard pending and staged entries, optionally restricted to one agent."""
        agent_dir = self._agent_path(agent_id) if agent_id else self.sandbox_root
        count = 0
        with self._lock:
            to_discard = [
                (k, e)
                for k, e in self._entries.items()
                if (not agent_id or e.agent_id == agent_id) and e.status in ("pending", "staged")
            ]
            for key, entry in to_discard:
                entry.status = "discarded"
                count += 1
                # Clean up path_index
                rel_path = entry.path
                if rel_path in self._path_index:
                    try:
                        self._path_index[rel_path].remove(key)
                        if not self._path_index[rel_path]:
                            del self._path_index[rel_path]
                    except ValueError:
                        logger.debug("cell_sandbox: path index key already removed, skipping")
            self._persist_state()

        try:
            if agent_dir.exists():
                shutil.rmtree(str(agent_dir))
                if agent_id:
                    self.register_agent(agent_id)
        except Exception as e:
            return {"success": True, "discarded": count, "warning": str(e)}

        return {"success": True, "discarded": count}

    def get_entry_summary(self, rel_path: str, agent_id: str = "") -> dict | None:
        """Get a lightweight structured summary for an entry.

        Cache hierarchy:
          L1 — SandboxEntry._summary_cache (per-instance)
          L2 — CellSandbox._summary_cache (shared, keyed by path, invalidated on write)
        """
        with self._lock:
            cached = self._summary_cache.get(rel_path)
            if cached is not None:
                return cached
        entry = self.get_entry(rel_path, agent_id)
        if not entry:
            return None
        summary = entry.to_summary()
        with self._lock:
            self._summary_cache[rel_path] = summary
        return summary

    def get_entry(self, rel_path: str, agent_id: str = "") -> SandboxEntry | None:
        """Get a sandbox entry by relative path.

        If ``agent_id`` is given, returns that agent's entry for the file.
        Otherwise returns the latest entry across all agents.
        """
        with self._lock:
            if agent_id:
                return self._entries.get(f"{rel_path}::{agent_id}")
            best: SandboxEntry | None = None
            best_ts = 0.0
            for key, entry in self._entries.items():
                if entry.modified_at > best_ts and key.startswith(rel_path + "::"):
                    best = entry
                    best_ts = entry.modified_at
            return best

    def get_entries(self, agent_id: str = "") -> list[SandboxEntry]:
        """Get all entries, optionally filtered by agent.

        When no agent specified, returns the latest entry per file path.
        """
        with self._lock:
            if agent_id:
                return [e for e in self._entries.values() if e.agent_id == agent_id]
            best_per_path: dict[str, SandboxEntry] = {}
            for entry in self._entries.values():
                prev = best_per_path.get(entry.path)
                if prev is None or entry.modified_at > prev.modified_at:
                    best_per_path[entry.path] = entry
            return list(best_per_path.values())

    def status(self) -> dict:
        """Return current sandbox status for this cell."""
        with self._lock:
            pending = sum(1 for e in self._entries.values() if e.status == "pending")
            staged = sum(1 for e in self._entries.values() if e.status == "staged")
            flushed = sum(1 for e in self._entries.values() if e.status == "flushed")
            return {
                "cell_id": self.cell_id,
                "agents": list(self._agents.keys()),
                "entries": len(self._entries),
                "pending": pending,
                "staged": staged,
                "flushed": flushed,
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
