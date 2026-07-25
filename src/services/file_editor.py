"""File Editor — Diff语义编辑引擎 + 原子批量 + Patch系统 + Undo/Redo

架构:
  FileEditor (services/file_editor.py)
  ├── diff_edit()       — 语义 search/replace，带上下文容错匹配
  ├── batch_edit()      — 原子化多文件编辑（全成功或全回滚）
  ├── patch_create()    — 从变更创建 patch
  ├── patch_apply()     — 应用 patch
  ├── patch_revert()    — 回滚 patch
  └── HistoryStack      — 文件操作历史栈 + reversal 反推

API (通过 LOG_ROUTES 模式注册):
  POST /api/fs/edit         — 语义编辑
  POST /api/fs/batch_edit   — 原子批量编辑
  GET  /api/fs/history      — 操作历史
  POST /api/fs/undo         — 回滚
  POST /api/fs/redo         — 重做
  POST /api/fs/patch        — 从变更创建 patch
  POST /api/fs/patch/apply  — 应用 patch
  POST /api/fs/patch/revert — 回滚 patch
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 1. Core data models
# ══════════════════════════════════════════════════════════════════════


@dataclass
class DiffEdit:
    """单次语义编辑操作。

    old_str: 要替换的原始文本（支持上下文容错匹配）
    new_str: 替换后的文本
    path:    文件路径
    description: 人类可读的编辑说明
    """
    path: str
    old_str: str
    new_str: str
    description: str = ""
    start_line: int = 0       # 精确行号（可选）
    end_line: int = 0
    case_sensitive: bool = True

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "old_str": self.old_str[:100],
            "new_str": self.new_str[:100],
            "description": self.description,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass
class EditOperation:
    """已执行的一次编辑操作（用于历史栈）。"""
    id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:12])
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
    """结构化的补丁，可序列化为文件。"""
    id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:12])
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
    """文件编辑引擎 — Diff语义匹配 + 原子批量 + 历史栈。"""

    def __init__(self, max_history: int = 100):
        self._history: list[EditOperation] = []
        self._redo_stack: list[EditOperation] = []
        self._lock = threading.RLock()
        self._max_history = max_history

    # ── Diff 语义编辑 ──

    def diff_edit(self, edit: DiffEdit) -> dict:
        """执行语义 search/replace 编辑。

        支持：
          - 精确匹配（默认）
          - 上下文容错匹配（忽略头尾空白差异）
          - 行号范围限定
        """
        path = Path(edit.path)
        if not path.exists():
            return {"success": False, "error": f"file not found: {edit.path}"}

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"read failed: {e}"}

        old = edit.old_str
        new = edit.new_str

        # 行号范围截取
        if edit.start_line > 0 and edit.end_line > 0:
            lines = content.splitlines(keepends=True)
            if edit.start_line < 1 or edit.end_line > len(lines):
                return {"success": False, "error": "line range out of bounds"}
            target = "".join(lines[edit.start_line - 1:edit.end_line])
        else:
            target = content

        # 语义匹配
        idx = self._match(target, old, edit.case_sensitive)
        if idx < 0:
            return {"success": False, "error": "old_str not found (try adjusting context)"}

        new_content = target[:idx] + new + target[idx + len(old):]

        # 写回文件
        if edit.start_line > 0 and edit.end_line > 0:
            lines[edit.start_line - 1:edit.end_line] = [new_content]
            final = "".join(lines)
        else:
            final = new_content

        try:
            path.write_text(final, encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"write failed: {e}"}

        op = EditOperation(
            edits=[{"path": str(path), "old": old, "new": new,
                     "line": edit.start_line or 1}],
            description=edit.description or f"edit {path.name}",
        )
        self._push(op)

        return {
            "success": True,
            "path": str(path),
            "operation_id": op.id,
            "description": op.description,
        }

    def _match(self, content: str, pattern: str, case_sensitive: bool = True) -> int:
        """语义匹配 — 先精确匹配，再上下文容错匹配。"""
        # 1. 精确匹配
        if case_sensitive:
            idx = content.find(pattern)
        else:
            idx = content.lower().find(pattern.lower())
        if idx >= 0:
            return idx

        # 2. 容错匹配 — 忽略两端空白差异
        stripped = pattern.strip()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if stripped in line:
                # 还原到 content 中的位置
                pos = sum(len(l) + 1 for l in lines[:i])
                return pos + line.find(stripped)

        return -1

    # ── 原子批量编辑 ──

    def batch_edit(self, edits: list[DiffEdit], description: str = "",
                   agent_id: str = "") -> dict:
        """原子化多文件编辑 — 全成功或全回滚。

        流程：
          1. 对所有文件做 dry-run 验证
          2. 逐一执行编辑
          3. 任一失败 → 全部回滚
          4. 全部成功 → 记录一个原子操作
        """
        if not edits:
            return {"success": False, "error": "no edits provided"}

        # Phase 1: Dry-run 验证
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

        # Phase 2: 执行编辑
        applied: list[dict] = []
        try:
            for i, edit, new_content in prepared:
                Path(edit.path).write_text(new_content, encoding="utf-8")
                applied.append({
                    "path": edit.path,
                    "old": edit.old_str,
                    "new": edit.new_str[:100],
                    "line": edit.start_line or 1,
                })
        except Exception as e:
            # Phase 3: 回滚全部
            for path_str, orig in snapshots:
                try:
                    Path(path_str).write_text(orig, encoding="utf-8")
                except Exception as re:
                    logger.error("batch_edit rollback failed: %s: %s", path_str, re)
            return {"success": False, "error": f"write failed, all rolled back: {e}",
                    "applied_before_rollback": len(applied)}

        # 记录操作
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
        """回滚最近一次（或指定）操作。"""
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

        # 逆序回滚
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
            except Exception as ex:
                return {"success": False, "error": f"undo failed: {e['path']}: {ex}"}

        with self._lock:
            self._history.remove(op)
            self._redo_stack.append(op)

        return {"success": True, "operation_id": op.id,
                "description": op.description, "type": "undo"}

    def redo(self) -> dict:
        """重做最近一次回滚的操作。"""
        with self._lock:
            if not self._redo_stack:
                return {"success": False, "error": "nothing to redo"}
            op = self._redo_stack.pop()

        # 重做所有编辑
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
            except Exception as ex:
                return {"success": False, "error": f"redo failed: {e['path']}: {ex}"}

        self._push(op)
        return {"success": True, "operation_id": op.id,
                "description": op.description, "type": "redo"}

    # ── 历史查询 ──

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

    # ── 内部 ──

    def _push(self, op: EditOperation) -> None:
        with self._lock:
            self._history.append(op)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            self._redo_stack.clear()


# ══════════════════════════════════════════════════════════════════════
# 3. Patch 系统
# ══════════════════════════════════════════════════════════════════════


class PatchManager:
    """Patch 管理 — 创建/应用/回滚/序列化。"""

    def __init__(self, engine: EditEngine, patch_dir: str = ""):
        self._engine = engine
        self._patches: dict[str, Patch] = {}
        self._lock = threading.RLock()
        from kernel.platform import get_config_dir
        self._patch_dir = Path(patch_dir or get_config_dir()) / "patches"
        self._patch_dir.mkdir(parents=True, exist_ok=True)

    def create_from_history(self, operation_id: str, description: str = "",
                            author: str = "") -> dict:
        """从历史操作创建 patch。"""
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
            # 持久化到磁盘
            self._save(patch)

        return {"success": True, "patch": patch.to_dict()}

    def apply(self, patch_id: str) -> dict:
        """应用一个 patch。"""
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
        """回滚一个已应用的 patch。"""
        with self._lock:
            patch = self._patches.get(patch_id)
        if not patch:
            return {"success": False, "error": f"patch not found: {patch_id}"}
        if not patch.applied:
            return {"success": False, "error": "patch not applied"}
        if patch.reverted:
            return {"success": False, "error": "patch already reverted"}

        # 反转 changes 并执行 undo
        edits = []
        for c in reversed(patch.changes):
            edits.append(DiffEdit(
                path=c["path"],
                old_str=c["new"],   # 新旧互换
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
        """持久化 patch 到磁盘。"""
        try:
            path = self._patch_dir / f"{patch.id}.json"
            path.write_text(patch.to_json(), encoding="utf-8")
        except Exception as e:
            logger.warning("patch save failed: %s", e)

    def _load_all(self) -> None:
        """启动时从磁盘加载所有 patch。"""
        if not self._patch_dir.exists():
            return
        for f in self._patch_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                patch = Patch(**{k: v for k, v in data.items()
                                 if k in Patch.__dataclass_fields__})
                self._patches[patch.id] = patch
            except Exception as e:
                logger.warning("patch load failed: %s: %s", f.name, e)


# ══════════════════════════════════════════════════════════════════════
# 4. 全局单例
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
    """POST /api/fs/edit — 语义编辑文件"""
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
    """POST /api/fs/batch_edit — 原子化多文件编辑"""
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
    """GET /api/fs/history — 文件操作历史"""
    b = body or {}
    limit = b.get("limit", 50)
    return get_engine().history(limit=limit)


def handle_fs_undo(body: dict | None = None) -> dict:
    """POST /api/fs/undo — 回滚操作"""
    b = body or {}
    op_id = b.get("operation_id", "")
    return get_engine().undo(operation_id=op_id)


def handle_fs_redo(body: dict | None = None) -> dict:
    """POST /api/fs/redo — 重做操作"""
    return get_engine().redo()


def handle_fs_patch_create(body: dict | None = None) -> dict:
    """POST /api/fs/patch — 从历史操作创建 patch"""
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
    """POST /api/fs/patch/apply — 应用 patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().apply(patch_id)


def handle_fs_patch_revert(body: dict | None = None) -> dict:
    """POST /api/fs/patch/revert — 回滚 patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().revert(patch_id)


def handle_fs_patch_list(body: dict | None = None) -> dict:
    """GET /api/fs/patches — 列出所有 patch"""
    return get_patch_manager().list_patches()


def handle_fs_patch_get(body: dict | None = None) -> dict:
    """POST /api/fs/patch/get — 获取单个 patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().get_patch(patch_id)


# ── 路由注册 ──

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
