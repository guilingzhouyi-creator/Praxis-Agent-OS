"""Sandbox — copy-on-write isolation for Agent file operations.

Model:
  Read:   from real project (read-only, shared)
  Write:  to sandbox (copy-on-write, per-Agent)
  Flush:  L3 approves → sandbox → real project
  Discard: sandbox deleted, project unchanged
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox_diff import check_conflict, compute_hunks

from l1.kernel import get_rwlock
from l1.kernel.params.api import ENV_SANDBOX_ROOT
from l1.kernel.params.system import (
    HASH_TRUNC_LONG,
    SANDBOX_STATE_TEMPLATE,
)
from l1.kernel.paths import get_paths as _gp
from l1.kernel.platform import get_temp_dir as _get_temp_dir

logger = logging.getLogger(__name__)

# ── Diff color scheme — customizable via API ──

_DEFAULT_COLOR_SCHEME: dict[str, str] = {
    "logic_change":  "\033[31m",   # red
    "reformat":      "\033[34m",   # blue
    "comment_only":  "\033[32m",   # green
    "import_change": "\033[33m",   # yellow
    "import_added":  "\033[33m",   # yellow
    "rename":        "\033[36m",   # cyan
    "structural":    "\033[90m",   # bright black
    "mixed":         "\033[35m",   # magenta
    "added":         "\033[32m",   # green
    "removed":       "\033[31m",   # red
}
_RESET = "\033[0m"

_COLOR_SCHEME: dict[str, str] = dict(_DEFAULT_COLOR_SCHEME)


def get_color_scheme() -> dict[str, str]:
    """Get current color scheme.

    Precedence (highest first):
      1. Runtime overrides (via API)
      2. YAML config ``diff.colors``
      3. Built-in defaults
    """
    result = dict(_DEFAULT_COLOR_SCHEME)
    try:
        from l3.config.settings_center import get_center
        cfg_colors = get_center().get("diff.colors", {})
        if cfg_colors and isinstance(cfg_colors, dict):
            result.update(cfg_colors)
    except Exception:
        logger.debug("cell_sandbox: diff colors config load failed, using defaults", exc_info=True)
    result.update(_COLOR_SCHEME)  # runtime overrides on top
    return result


def set_color_scheme(scheme: dict[str, str]) -> None:
    """Update color scheme for semantic categories."""
    _COLOR_SCHEME.update(scheme)


def reset_color_scheme() -> None:
    """Reset the sandbox diff color scheme to defaults."""
    _COLOR_SCHEME.clear()
    _COLOR_SCHEME.update(_DEFAULT_COLOR_SCHEME)


# ── Sandbox timing constants ──

# Configurable sandbox root — cross-platform: falls back to OS temp dir
_DEFAULT_SANDBOX = os.path.join(_get_temp_dir(), "praxis-sandbox")
_SANDBOX_ROOT = os.environ.get(ENV_SANDBOX_ROOT, _DEFAULT_SANDBOX)


@dataclass
class SandboxEntry:
    """Single file change record in the sandbox.

    ``hunks`` is a list of structured diff hunks (line-level).
    Each hunk::

        {"type": "modified",           # "added" | "removed" | "modified"
         "original_start": int, "original_end": int,
         "modified_start": int, "modified_end": int,
         "added_lines": [str], "removed_lines": [str],
         "context_before": [str], "context_after": [str],
         "changes": [                  # character-level (VSCode ICharChange-equivalent)
           {"original_start": {"line":int,"col":int}, "original_end": {"line":int,"col":int},
            "modified_start": {"line":int,"col":int}, "modified_end": {"line":int,"col":int}}
         ],
         "semantic": str}              # e.g. "logic_change: change return x+1 to x*2"
    """
    path: str          # relative path in project
    sandbox_path: str  # absolute path in sandbox
    agent_id: str
    tool_name: str = ""      # tool that created this entry (e.g. "write_file", "replace_string")
    status: str = "pending"   # pending | staged | flushed | discarded
    original_hash: str = ""
    modified_at: float = field(default_factory=time.time)
    # Structured diff (populated by write())
    hunks: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {"additions": 0, "deletions": 0, "hunks": 0})
    # HTN task context
    task_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    # Conflict detection
    conflict_level: str = "none"   # "none" | "warn" | "block" | "ping_pong"

    def to_serializable(self) -> dict:
        """Serialize to a JSON-safe dict for _persist_state."""
        return {
            "path": self.path, "sandbox_path": self.sandbox_path,
            "agent_id": self.agent_id, "tool_name": self.tool_name,
            "status": self.status,
            "original_hash": self.original_hash, "modified_at": self.modified_at,
            "hunks": self.hunks, "stats": self.stats,
            "task_id": self.task_id, "depends_on": self.depends_on,
            "conflict_level": self.conflict_level,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SandboxEntry:
        """Restore from a serialized dict (for _restore_state)."""
        return cls(
            path=d["path"], sandbox_path=d["sandbox_path"],
            agent_id=d["agent_id"], tool_name=d.get("tool_name", ""),
            status=d.get("status", "pending"),
            original_hash=d.get("original_hash", ""),
            modified_at=d.get("modified_at", 0.0),
            hunks=d.get("hunks", []),
            stats=d.get("stats", {"additions": 0, "deletions": 0, "hunks": 0}),
            task_id=d.get("task_id", ""),
            depends_on=d.get("depends_on", []),
            conflict_level=d.get("conflict_level", "none"),
        )

    def to_human_readable(self) -> dict:
        """Reconstruct unified-diff text + summary from structured hunks.

        Returns::

            {"success": True,
             "path": self.path,
             "diff": "@@ -1,3 +1,4 @@...",     # unified diff text
             "summary": "+2/-1 in foo.py",
             "stats": {"additions": 2, "deletions": 1, "hunks": 1},
             "semantic": "logic_change"}
        """
        if not self.hunks:
            return {
                "success": True,
                "path": self.path,
                "diff": "",
                "summary": f"no changes in {self.path}",
                "stats": self.stats,
                "semantic": "",
            }

        lines: list[str] = []
        start_line = 1
        end_line = 1

        for h in self.hunks:
            orig_start = h.get("original_start", 1)
            orig_end = h.get("original_end", 0) or orig_start
            mod_start = h.get("modified_start", 1)
            mod_end = h.get("modified_end", 0) or mod_start
            orig_count = orig_end - orig_start + 1 if h["type"] != "insert" else 0
            mod_count = mod_end - mod_start + 1 if h["type"] != "delete" else 0

            lines.append(f"@@ -{orig_start},{orig_count} +{mod_start},{mod_count} @@")

            ctx_lines = [(" " + l.rstrip("\n")) for l in h.get("context_before", [])]
            for cl in ctx_lines:
                lines.append(cl)

            for l in h.get("removed_lines", []):
                lines.append("-" + l.rstrip("\n"))
            for l in h.get("added_lines", []):
                lines.append("+" + l.rstrip("\n"))

            ctx_after = [(" " + l.rstrip("\n")) for l in h.get("context_after", [])]
            for cl in ctx_after:
                lines.append(cl)

        diff_text = "\n".join(lines)

        # Pick a semantic label — prefer the most meaningful
        semantic = ""
        for h in self.hunks:
            s = h.get("semantic", "")
            if s and s not in ("", "structural"):
                semantic = s
                break
        if not semantic:
            for h in self.hunks:
                s = h.get("semantic", "")
                if s:
                    semantic = s
                    break
        if not semantic:
            # Fallback: derive from hunk types
            has_add = any(h["type"] == "insert" for h in self.hunks)
            has_del = any(h["type"] == "delete" for h in self.hunks)
            semantic = "mixed" if (has_add and has_del) else ("added" if has_add else "removed")

        a = self.stats.get("additions", 0)
        d = self.stats.get("deletions", 0)
        summary = f"+{a}/-{d} in {self.path}"
        if semantic:
            summary += f" ({semantic})"

        return {
            "success": True,
            "path": self.path,
            "diff": diff_text,
            "summary": summary,
            "stats": self.stats,
            "semantic": semantic,
        }

    _summary_cache: dict | None = None

    def to_summary(self) -> dict:
        """Lightweight structured summary, cached on first call.

        Returns::

            {"success": True,
             "path": self.path,
             "agent_id": self.agent_id,
             "tool_name": self.tool_name,
             "task_id": self.task_id,
             "stats": {"additions": N, "deletions": N, "hunks": N},
             "semantic": "logic_change",
             "ranges": [{"start": 10, "end": 15}, ...],
             "by_type": {"replace": 2, "insert": 0, "delete": 1},
             "modified_at": self.modified_at}
        """
        if self._summary_cache is not None:
            return self._summary_cache

        if not self.hunks:
            result = {
                "success": True,
                "path": self.path,
                "agent_id": self.agent_id,
                "tool_name": self.tool_name,
                "task_id": self.task_id,
                "stats": self.stats,
                "semantic": "",
                "ranges": [],
                "by_type": {},
                "modified_at": self.modified_at,
            }
            self._summary_cache = result
            return result

        ranges: list[dict[str, int]] = []
        by_type: dict[str, int] = {}
        semantic = ""

        for h in self.hunks:
            t = h.get("type", "replace")
            by_type[t] = by_type.get(t, 0) + 1
            start = h.get("original_start", 1) or h.get("modified_start", 1)
            end = (h.get("original_end") or h.get("modified_end") or start)
            ranges.append({"start": start, "end": end})
            s = h.get("semantic", "")
            if s and s not in ("", "structural"):
                semantic = s

        if not semantic:
            has_add = any(h["type"] == "insert" for h in self.hunks)
            has_del = any(h["type"] == "delete" for h in self.hunks)
            semantic = "mixed" if (has_add and has_del) else ("added" if has_add else "removed")

        result = {
            "success": True,
            "path": self.path,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "task_id": self.task_id,
            "stats": self.stats,
            "semantic": semantic,
            "ranges": ranges,
            "by_type": by_type,
            "modified_at": self.modified_at,
        }
        self._summary_cache = result
        return result

    def to_colored_diff(self, scheme: dict[str, str] | None = None) -> dict:
        """Unified diff text with ANSI color codes applied per semantic type.

        Args:
            scheme: Optional override color scheme.
                    Falls back to module-level ``_COLOR_SCHEME``.

        Returns::

            {"success": True, "path": "...", "diff": "...",
             "stats": {...}, "semantic": "..."}
        """
        if scheme is None:
            scheme = _COLOR_SCHEME
        hr = self.to_human_readable()
        if not hr.get("success") or not hr.get("diff"):
            return hr
        s = hr["semantic"]
        color = scheme.get(s, "")
        colored_lines: list[str] = []
        for line in hr["diff"].split("\n"):
            if line.startswith("+") or line.startswith("-"):
                colored_lines.append(f"{color}{line}{_RESET}")
            else:
                colored_lines.append(line)
        hr["diff"] = "\n".join(colored_lines)
        hr["colored"] = True
        return hr





class CellSandbox:
    """Sandbox for one Cell. Contains per-Agent write layers — persisted to JSON."""

    def __init__(self, cell_id: str, project_root: str, sandbox_root: str,
                 state_path: str = ""):
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
                "entries": {eid: e.to_serializable()
                            for eid, e in self._entries.items()},
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
            logger.info("sandbox restored: %d agents, %d entries",
                        len(self._agents), len(self._entries))
        except Exception as e:
            logger.warning("sandbox restore failed: %s", e)

    def register_agent(self, agent_id: str) -> Path:
        agent_dir = self.sandbox_root / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._agents[agent_id] = agent_dir
            self._persist_state()
        return agent_dir

    def _get_old_content(self, rel_path: str, agent_id: str,
                         depends_on: list[str] | None = None) -> tuple[str, str]:
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

    def read(self, rel_path: str, agent_id: str,
             depends_on: list[str] | None = None) -> dict:
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
                return {"success": True, "content": content,
                        "source": "sandbox", "path": str(sandbox_file),
                        "agent_id": agent_id}
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
                        return {"success": True, "content": content,
                                "source": "upstream", "path": str(up_file),
                                "agent_id": upstream_id}
                    except Exception as e:
                        return {"success": False, "error": str(e)}

        # 3. Project base
        real_file = self.project_root / safe_rel
        if real_file.exists():
            try:
                content = real_file.read_text(encoding="utf-8")
                return {"success": True, "content": content,
                        "source": "project", "path": str(real_file)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "file not found"}

    def write(self, rel_path: str, content: str, agent_id: str,
              task_id: str = "", tool_name: str = "",
              depends_on: list[str] | None = None) -> dict:
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
            new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:HASH_TRUNC_LONG]

            # 2. Compute structured diff with agent/tool attribution
            now = time.time()
            hunks = compute_hunks(old_content, content,
                                  agent_id=agent_id, tool_name=tool_name,
                                  timestamp=now)
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
                path=safe_rel, sandbox_path=str(target),
                agent_id=agent_id, tool_name=tool_name, status="pending",
                original_hash=old_hash,
                hunks=hunks, stats=stats,
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
                ebus.emit(Signal(
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
                ))
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
        staged = []
        with self._lock:
            for key, entry in self._entries.items():
                if entry.agent_id == agent_id and entry.status == "pending":
                    entry.status = "staged"
                    staged.append(entry.path)
            self._persist_state()
        return {"success": True, "staged": staged, "count": len(staged)}

    def flush(self, agent_id: str, rel_paths: list[str] | None = None) -> dict:
        """Flush approved sandbox changes to the real project."""
        flushed = []
        with self._lock:
            targets = [(entry, entry.path) for entry in self._entries.values()
                       if entry.agent_id == agent_id and entry.status == "staged"
                       and (rel_paths is None or entry.path in rel_paths)]

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
        agent_dir = self._agent_path(agent_id) if agent_id else self.sandbox_root
        count = 0
        with self._lock:
            to_discard = [(k, e) for k, e in self._entries.items()
                          if (not agent_id or e.agent_id == agent_id)
                          and e.status in ("pending", "staged")]
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
                if key.startswith(rel_path + "::"):
                    if entry.modified_at > best_ts:
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
            # each other's entries via the shared sandbox_state path.
            state_path = str(self._sandbox_root / SANDBOX_STATE_TEMPLATE.format(cell_id=cell_id))
            sb = CellSandbox(cell_id, project_root, str(self._sandbox_root),
                             state_path=state_path)
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
