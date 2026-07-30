"""File Editor — Diff Semantic Edit Engine + Atomic Batch + Patch System + Undo/Redo

Architecture:
  FileEditor (services/file_editor.py)
  ├── diff_edit()       — Semantic search/replace with context-tolerant matching
  ├── batch_edit()      — Atomic multi-file editing (all succeed or all roll back)
  ├── patch_create()    — Create a patch from changes
  ├── patch_apply()     — Apply a patch
  ├── patch_revert()    — Revert a patch
  └── HistoryStack      — File operation history stack + reversal inference

API (via LOG_ROUTES registration):
  POST /api/fs/edit         — Semantic edit
  POST /api/fs/batch_edit   — Atomic batch edit
  GET  /api/fs/history      — Operation history
  POST /api/fs/undo         — Rollback
  POST /api/fs/redo         — Redo
  POST /api/fs/patch        — Create patch from changes
  POST /api/fs/patch/apply  — Apply patch
  POST /api/fs/patch/revert — Revert patch
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time

from l1.kernel.params.system import HASH_TRUNC_MEDIUM, LOG_TRUNC_100, PATCH_JSON_FILE
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 1. Core data models
# ══════════════════════════════════════════════════════════════════════


@dataclass
class DiffEdit:
    """Single semantic edit operation.

    old_str: Original text to replace (supports context-tolerant matching)
    new_str: Replacement text
    path:    File path
    description: Human-readable edit description
    """
    path: str
    old_str: str
    new_str: str
    description: str = ""
    start_line: int = 0       # Exact line number (optional)
    end_line: int = 0
    case_sensitive: bool = True

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "old_str": self.old_str[:LOG_TRUNC_100],
            "new_str": self.new_str[:LOG_TRUNC_100],
            "description": self.description,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass
class EditOperation:
    """A single executed edit operation (used for history stack)."""
    id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:HASH_TRUNC_MEDIUM])
    timestamp: float = field(default_factory=time.time)
    edits: list[dict] = field(default_factory=list)   # [{"path", "old", "new", "line"}, ...]
    description: str = ""
    agent_id: str = ""
    success: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "edits": self.edits,
            "description": self.description,
            "agent_id": self.agent_id,
            "success": self.success,
        }


@dataclass
class Patch:
    """Structured patch, serializable to file."""
    id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:HASH_TRUNC_MEDIUM])
    created_at: float = field(default_factory=time.time)
    description: str = ""
    author: str = ""
    changes: list[dict] = field(default_factory=list)  # [{"path", "old", "new", "line"}, ...]
    applied: bool = False
    reverted: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "description": self.description,
            "author": self.author,
            "changes": self.changes,
            "applied": self.applied,
            "reverted": self.reverted,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Patch:
        data = json.loads(raw)
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════════
# 2. Edit Engine
# ══════════════════════════════════════════════════════════════════════


class EditEngine:
    """File edit engine — Diff semantic matching + atomic batch + history stack."""

    def __init__(self, max_history: int = 100):
        self._history: list[EditOperation] = []
        self._redo_stack: list[EditOperation] = []
        self._lock = threading.RLock()
        self._max_history = max_history

    # ── Diff Semantic Edit ──

    def diff_edit(self, edit: DiffEdit) -> dict:
        """Execute semantic search/replace edit.

        Supports:
          - Exact match (default)
          - Context-tolerant match (ignores leading/trailing whitespace differences)
          - Line range restriction
        """
        path = Path(edit.path)
        if not path.exists():
            return {"success": False, "error": f"file not found: {edit.path}"}

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {"success": False, "error": f"read failed: {e}"}

        old = edit.old_str
        new = edit.new_str

        # Line range extraction
        if edit.start_line > 0 and edit.end_line > 0:
            lines = content.splitlines(keepends=True)
            if edit.start_line < 1 or edit.end_line > len(lines):
                return {"success": False, "error": "line range out of bounds"}
            target = "".join(lines[edit.start_line - 1:edit.end_line])
        else:
            target = content

        # Semantic matching
        idx = self._match(target, old, edit.case_sensitive)
        if idx < 0:
            return {"success": False, "error": "old_str not found (try adjusting context)"}

        new_content = target[:idx] + new + target[idx + len(old):]

        # Write back to file
        if edit.start_line > 0 and edit.end_line > 0:
            lines[edit.start_line - 1:edit.end_line] = [new_content]
            final = "".join(lines)
        else:
            final = new_content

        try:
            from l3.resource_buffer.manager import get_manager
            get_manager().stage(str(path), final, op="edit")
        except (ImportError, AttributeError) as e:
            return {"success": False, "error": f"buffer stage failed: {e}"}

        op = EditOperation(
            edits=[{"path": str(path), "old": old, "new": new,
                     "line": edit.start_line or 1}],
            description=edit.description or f"edit {path.name}",
        )
        self._push(op)

        # Reference Channel: record human correction for training data
        try:
            from l3.bus.reference_channel import get_rc as _rc
            _rc().human_correction("", "", "content", old, new, reason=f"edit {path.name}")
        except (ImportError, AttributeError):
            logger.debug("file_editor: rc correction failed")

        return {
            "success": True,
            "path": str(path),
            "operation_id": op.id,
            "description": op.description,
        }

    def _match(self, content: str, pattern: str, case_sensitive: bool = True) -> int:
        """Semantic matching — first exact match, then context-tolerant match."""
        # 1. Exact match
        if case_sensitive:
            idx = content.find(pattern)
        else:
            idx = content.lower().find(pattern.lower())
        if idx >= 0:
            return idx

        # 2. Fault-tolerant match — ignore leading/trailing whitespace differences
        stripped = pattern.strip()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if stripped in line:
                # Restore position in content
                pos = sum(len(l) + 1 for l in lines[:i])
                return pos + line.find(stripped)

        return -1

    # ── Atomic Batch Edit ──

    def batch_edit(self, edits: list[DiffEdit], description: str = "",
                   agent_id: str = "") -> dict:
        """Atomic multi-file edit — all succeed or all roll back.

        Steps:
          1. Dry-run validation on all files
          2. Execute edits one by one
          3. Any failure → roll back all
          4. All succeed → record as one atomic operation
        """
        if not edits:
            return {"success": False, "error": "no edits provided"}

        # Phase 1: Dry-run validation
        snapshots: list[tuple[str, str]] = []  # (path, original_content)
        prepared: list[tuple[int, DiffEdit, str]] = []  # (idx, edit, new_content)

        for i, edit in enumerate(edits):
            path = Path(edit.path)
            if not path.exists():
                return {"success": False, "error": f"file not found: {edit.path}",
                        "edit_index": i}

            try:
                content = path.read_text(encoding="utf-8")
            except Exception as e:
                return {"success": False, "error": f"read failed: {edit.path}: {e}",
                        "edit_index": i}

            snapshots.append((str(path), content))

            old = edit.old_str
            new = edit.new_str
            idx = self._match(content, old, edit.case_sensitive)
            if idx < 0:
                return {"success": False, "error": f"old_str not found: {edit.path}",
                        "edit_index": i}

            new_content = content[:idx] + new + content[idx + len(old):]
            prepared.append((i, edit, new_content))

        # Phase 2: Execute edits
        applied: list[dict] = []
        try:
            for i, edit, new_content in prepared:
                Path(edit.path).write_text(new_content, encoding="utf-8")
                applied.append({
                    "path": edit.path,
                    "old": edit.old_str,
                    "new": edit.new_str[:LOG_TRUNC_100],
                    "line": edit.start_line or 1,
                })
        except (OSError, ValueError) as e:
            # Phase 3: Roll back all
            for path_str, orig in snapshots:
                try:
                    Path(path_str).write_text(orig, encoding="utf-8")
                except OSError as re:
                    logger.error("batch_edit rollback failed: %s: %s", path_str, re)
            return {"success": False, "error": f"write failed, all rolled back: {e}",
                    "applied_before_rollback": len(applied)}

        # Record operation
        op = EditOperation(
            edits=applied,
            description=description or f"batch edit: {len(edits)} files",
            agent_id=agent_id,
        )
        self._push(op)

        return {
            "success": True,
            "operation_id": op.id,
            "files": len(applied),
            "edits": applied,
            "description": op.description,
        }

    # ── Undo / Redo ──

    def undo(self, operation_id: str = "") -> dict:
        """Rollback the most recent (or specified) operation."""
        with self._lock:
            if not self._history:
                return {"success": False, "error": "nothing to undo"}

            if operation_id:
                op = next((o for o in reversed(self._history)
                          if o.id == operation_id), None)
            else:
                op = self._history[-1]

            if not op:
                return {"success": False, "error": f"operation not found: {operation_id}"}

        # Reverse order rollback
        for e in reversed(op.edits):
            path = Path(e["path"])
            if not path.exists():
                logger.warning("undo: file gone, skipping: %s", e["path"])
                continue
            try:
                content = path.read_text(encoding="utf-8")
                new_str = e["new"]
                old_str = e["old"]
                idx = self._match(content, new_str)
                if idx >= 0:
                    restored = content[:idx] + old_str + content[idx + len(new_str):]
                    path.write_text(restored, encoding="utf-8")
                else:
                    logger.warning("undo: cannot find new_str to revert: %s", e["path"])
            except OSError as ex:
                return {"success": False, "error": f"undo failed: {e['path']}: {ex}"}

        with self._lock:
            self._history.remove(op)
            self._redo_stack.append(op)

        return {"success": True, "operation_id": op.id,
                "description": op.description, "type": "undo"}

    def redo(self) -> dict:
        """Redo the most recently undone operation."""
        with self._lock:
            if not self._redo_stack:
                return {"success": False, "error": "nothing to redo"}
            op = self._redo_stack.pop()

        # Redo all edits
        for e in op.edits:
            path = Path(e["path"])
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8")
                old_str = e["old"]
                new_str = e["new"]
                idx = self._match(content, old_str)
                if idx >= 0:
                    restored = content[:idx] + new_str + content[idx + len(old_str):]
                    path.write_text(restored, encoding="utf-8")
            except OSError as ex:
                return {"success": False, "error": f"redo failed: {e['path']}: {ex}"}

        self._push(op)
        return {"success": True, "operation_id": op.id,
                "description": op.description, "type": "redo"}

    # ── History Query ──

    def history(self, limit: int = 50) -> dict:
        with self._lock:
            entries = [o.to_dict() for o in self._history[-limit:]]
            entries.reverse()
            return {
                "success": True,
                "count": len(entries),
                "entries": entries,
                "undo_available": len(self._history),
                "redo_available": len(self._redo_stack),
            }

    # ── Internal ──

    def _push(self, op: EditOperation) -> None:
        with self._lock:
            self._history.append(op)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            self._redo_stack.clear()


# ══════════════════════════════════════════════════════════════════════
# 3. Patch System
# ══════════════════════════════════════════════════════════════════════


class PatchManager:
    """Patch management — create/apply/revert/serialize."""

    def __init__(self, engine: EditEngine, patch_dir: str = ""):
        self._engine = engine
        self._patches: dict[str, Patch] = {}
        self._lock = threading.RLock()
        from l1.kernel.platform import get_config_dir
        self._patch_dir = Path(patch_dir or get_config_dir()) / "patches"
        self._patch_dir.mkdir(parents=True, exist_ok=True)

    def create_from_history(self, operation_id: str, description: str = "",
                            author: str = "") -> dict:
        """Create a patch from history operations."""
        with self._engine._lock:
            op = next((o for o in self._engine._history
                      if o.id == operation_id), None)
        if not op:
            return {"success": False, "error": f"operation not found: {operation_id}"}

        patch = Patch(
            description=description or op.description,
            author=author,
            changes=op.edits,
        )

        with self._lock:
            self._patches[patch.id] = patch
            # Persist to disk
            self._save(patch)

        return {"success": True, "patch": patch.to_dict()}

    def apply(self, patch_id: str) -> dict:
        """Apply a patch."""
        with self._lock:
            patch = self._patches.get(patch_id)
        if not patch:
            return {"success": False, "error": f"patch not found: {patch_id}"}
        if patch.applied:
            return {"success": False, "error": "patch already applied"}

        edits = []
        for c in patch.changes:
            edits.append(DiffEdit(
                path=c["path"],
                old_str=c["old"],
                new_str=c["new"],
                description=patch.description,
            ))

        result = self._engine.batch_edit(edits, description=f"patch: {patch.description}")
        if result.get("success"):
            patch.applied = True
            self._save(patch)

        return result

    def revert(self, patch_id: str) -> dict:
        """Revert an applied patch."""
        with self._lock:
            patch = self._patches.get(patch_id)
        if not patch:
            return {"success": False, "error": f"patch not found: {patch_id}"}
        if not patch.applied:
            return {"success": False, "error": "patch not applied"}
        if patch.reverted:
            return {"success": False, "error": "patch already reverted"}

        # Reverse changes and execute undo
        edits = []
        for c in reversed(patch.changes):
            edits.append(DiffEdit(
                path=c["path"],
                old_str=c["new"],   # Swap old and new
                new_str=c["old"],
                description=f"revert: {patch.description}",
            ))

        result = self._engine.batch_edit(edits,
                                         description=f"revert patch: {patch.description}")
        if result.get("success"):
            patch.reverted = True
            self._save(patch)

        return result

    def list_patches(self) -> dict:
        with self._lock:
            return {
                "success": True,
                "count": len(self._patches),
                "patches": [p.to_dict() for p in self._patches.values()],
            }

    def get_patch(self, patch_id: str) -> dict:
        with self._lock:
            patch = self._patches.get(patch_id)
        if not patch:
            return {"success": False, "error": "patch not found"}
        return {"success": True, "patch": patch.to_dict()}

    def _save(self, patch: Patch) -> None:
        """Persist patch to disk."""
        try:
            path = self._patch_dir / PATCH_JSON_FILE.format(patch_id=patch.id)
            path.write_text(patch.to_json(), encoding="utf-8")
        except OSError as e:
            logger.warning("patch save failed: %s", e)

    def _load_all(self) -> None:
        """Load all patches from disk at startup."""
        if not self._patch_dir.exists():
            return
        for f in self._patch_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                patch = Patch(**{k: v for k, v in data.items()
                                 if k in Patch.__dataclass_fields__})
                self._patches[patch.id] = patch
            except (OSError, ValueError, json.JSONDecodeError) as e:
                logger.warning("patch load failed: %s: %s", f.name, e)


# ══════════════════════════════════════════════════════════════════════
# 4. Global Singleton
# ══════════════════════════════════════════════════════════════════════

_engine: EditEngine | None = None
_patch_manager: PatchManager | None = None
_engine_lock = threading.Lock()


def get_engine() -> EditEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = EditEngine()
    return _engine


def get_patch_manager() -> PatchManager:
    global _patch_manager
    if _patch_manager is None:
        with _engine_lock:
            if _patch_manager is None:
                _patch_manager = PatchManager(get_engine())
                _patch_manager._load_all()
    return _patch_manager


# ══════════════════════════════════════════════════════════════════════
# 5. API Handlers
# ══════════════════════════════════════════════════════════════════════


def handle_fs_edit(body: dict | None = None) -> dict:
    """POST /api/fs/edit — Semantic file edit"""
    b = body or {}
    path = b.get("path", "")
    old_str = b.get("old_str", "")
    new_str = b.get("new_str", "")
    if not path or not old_str:
        return {"success": False, "error": "path and old_str are required"}
    edit = DiffEdit(
        path=path,
        old_str=old_str,
        new_str=new_str or "",
        description=b.get("description", ""),
        start_line=b.get("start_line", 0),
        end_line=b.get("end_line", 0),
        case_sensitive=b.get("case_sensitive", True),
    )
    return get_engine().diff_edit(edit)


def handle_fs_batch_edit(body: dict | None = None) -> dict:
    """POST /api/fs/batch_edit — Atomic multi-file edit"""
    b = body or {}
    raw_edits = b.get("edits", [])
    if not raw_edits:
        return {"success": False, "error": "edits required"}
    edits = [DiffEdit(**e) for e in raw_edits]
    return get_engine().batch_edit(
        edits,
        description=b.get("description", ""),
        agent_id=b.get("agent_id", ""),
    )


def handle_fs_history(body: dict | None = None) -> dict:
    """GET /api/fs/history — File operation history"""
    b = body or {}
    limit = b.get("limit", 50)
    return get_engine().history(limit=limit)


def handle_fs_undo(body: dict | None = None) -> dict:
    """POST /api/fs/undo — Rollback operation"""
    b = body or {}
    op_id = b.get("operation_id", "")
    return get_engine().undo(operation_id=op_id)


def handle_fs_redo(body: dict | None = None) -> dict:
    """POST /api/fs/redo — Redo operation"""
    return get_engine().redo()


def handle_fs_patch_create(body: dict | None = None) -> dict:
    """POST /api/fs/patch — Create patch from history"""
    b = body or {}
    op_id = b.get("operation_id", "")
    if not op_id:
        return {"success": False, "error": "operation_id required"}
    return get_patch_manager().create_from_history(
        operation_id=op_id,
        description=b.get("description", ""),
        author=b.get("author", ""),
    )


def handle_fs_patch_apply(body: dict | None = None) -> dict:
    """POST /api/fs/patch/apply — Apply patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().apply(patch_id)


def handle_fs_patch_revert(body: dict | None = None) -> dict:
    """POST /api/fs/patch/revert — Revert patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().revert(patch_id)


def handle_fs_patch_list(body: dict | None = None) -> dict:
    """GET /api/fs/patches — List all patches"""
    return get_patch_manager().list_patches()


def handle_fs_patch_get(body: dict | None = None) -> dict:
    """POST /api/fs/patch/get — Get single patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().get_patch(patch_id)


# ── Route Registration ──

FS_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/fs/edit", handle_fs_edit, "Semantic file edit (search/replace)"),
    ("POST", "/api/fs/batch_edit", handle_fs_batch_edit, "Atomic batch multi-file edit"),
    ("POST", "/api/fs/history", handle_fs_history, "File operation history"),
    ("POST", "/api/fs/undo", handle_fs_undo, "Undo file operation"),
    ("POST", "/api/fs/redo", handle_fs_redo, "Redo file operation"),
    ("POST", "/api/fs/patch", handle_fs_patch_create, "Create patch from history"),
    ("POST", "/api/fs/patch/apply", handle_fs_patch_apply, "Apply patch"),
    ("POST", "/api/fs/patch/revert", handle_fs_patch_revert, "Revert patch"),
    ("POST", "/api/fs/patches", handle_fs_patch_list, "List all patches"),
    ("POST", "/api/fs/patch/get", handle_fs_patch_get, "Get patch detail"),
]
