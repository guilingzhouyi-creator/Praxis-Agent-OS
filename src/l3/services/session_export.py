"""Session Export — Session Export/Import/Snapshot Management

API:
  POST /api/session/export      — Export session as JSON
  POST /api/session/import      — Import session
  GET  /api/session/snapshots   — List snapshots
  POST /api/session/snapshot    — Create snapshot
  POST /api/session/snapshot/restore — Restore from snapshot
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from l1.kernel.platform import get_config_dir
from l1.kernel.params.system import HASH_TRUNC_MEDIUM, HASH_TRUNC_SHORT, SNAPSHOT_GLOB, SNAPSHOT_PATH_TEMPLATE

_SNAPSHOT_DIR = Path(get_config_dir()) / "snapshots"


# ══════════════════════════════════════════════════════════════════════
# 1. Data models
# ══════════════════════════════════════════════════════════════════════


@dataclass
class SessionExport:
    """Exportable session format."""
    version: int = 2
    session_id: str = ""
    agent_id: str = ""
    created_at: float = field(default_factory=time.time)
    exported_at: float = field(default_factory=time.time)
    messages: list[dict] = field(default_factory=list)
    turn_count: int = 0
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "exported_at": self.exported_at,
            "messages": self.messages,
            "turn_count": self.turn_count,
            "metadata": self.metadata,
            "tags": self.tags,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> SessionExport:
        data = json.loads(raw)
        version = data.get("version", 1)
        if version > 2:
            raise ValueError(f"unsupported export version: {version}")
        if version < 2:
            data = cls._migrate_v1_to_v2(data)
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})

    @staticmethod
    def _migrate_v1_to_v2(data: dict) -> dict:
        data["version"] = 2
        data.setdefault("tags", [])
        data.setdefault("metadata", {})
        return data


@dataclass
class Snapshot:
    """Session snapshot (includes full state)."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:HASH_TRUNC_MEDIUM])
    session_id: str = ""
    created_at: float = field(default_factory=time.time)
    label: str = ""
    data: SessionExport = field(default_factory=SessionExport)

    def file_path(self) -> Path:
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        return _SNAPSHOT_DIR / SNAPSHOT_PATH_TEMPLATE.format(snapshot_id=self.id)

    def save(self) -> dict:
        path = self.file_path()
        payload = {
            "id": self.id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "label": self.label,
            "data": self.data.to_dict(),
        }
        try:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            return {"success": True, "path": str(path), "snapshot_id": self.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def load(cls, snapshot_id: str) -> Snapshot | None:
        path = _SNAPSHOT_DIR / SNAPSHOT_PATH_TEMPLATE.format(snapshot_id=snapshot_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            export_data = data.get("data", {})
            export = SessionExport(**{k: v for k, v in export_data.items()
                                       if k in SessionExport.__dataclass_fields__})
            return cls(
                id=data.get("id", snapshot_id),
                session_id=data.get("session_id", ""),
                created_at=data.get("created_at", 0),
                label=data.get("label", ""),
                data=export,
            )
        except Exception as e:
            logger.warning("snapshot load failed: %s", e)
            return None


# ══════════════════════════════════════════════════════════════════════
# 2. Session Export Manager
# ══════════════════════════════════════════════════════════════════════


class SessionExportManager:
    """Session export/import/snapshot manager."""

    def __init__(self):
        self._lock = threading.Lock()
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def export_session(self, session_id: str = "",
                       agent_id: str = "", messages: list[dict] = None,
                       tags: list[str] = None,
                       metadata: dict = None) -> dict:
        """Export session as shareable JSON."""
        export = SessionExport(
            session_id=session_id or f"session-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}",
            agent_id=agent_id,
            messages=messages or [],
            turn_count=len(messages or []),
            tags=tags or [],
            metadata=metadata or {},
        )
        result = export.to_dict()
        return {
            "success": True,
            "session_id": export.session_id,
            "turn_count": export.turn_count,
            "exported_at": export.exported_at,
            "data": result,
        }

    def import_session(self, raw: str) -> dict:
        """Import session JSON."""
        try:
            export = SessionExport.from_json(raw)
            return {
                "success": True,
                "session_id": export.session_id,
                "agent_id": export.agent_id,
                "turn_count": export.turn_count,
                "created_at": export.created_at,
                "messages": export.messages,
                "metadata": export.metadata,
                "tags": export.tags,
            }
        except Exception as e:
            return {"success": False, "error": f"import failed: {e}"}

    # ── Snapshots ──

    def create_snapshot(self, session_id: str = "",
                        messages: list[dict] = None,
                        agent_id: str = "",
                        label: str = "") -> dict:
        """Create a snapshot of the current session."""
        export = SessionExport(
            session_id=session_id,
            agent_id=agent_id,
            messages=messages or [],
            turn_count=len(messages or []),
        )
        snapshot = Snapshot(
            session_id=session_id,
            label=label or f"snapshot {time.strftime('%H:%M:%S')}",
            data=export,
        )
        return snapshot.save()

    def list_snapshots(self) -> dict:
        """List all snapshots."""
        if not _SNAPSHOT_DIR.exists():
            return {"success": True, "snapshots": [], "count": 0}

        snapshots = []
        for f in sorted(_SNAPSHOT_DIR.glob(SNAPSHOT_GLOB),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                snapshots.append({
                    "id": data.get("id", f.stem),
                    "session_id": data.get("session_id", ""),
                    "label": data.get("label", ""),
                    "created_at": data.get("created_at", 0),
                    "turn_count": data.get("data", {}).get("turn_count", 0),
                })
            except Exception as e:
                logger.warning("snapshot list: %s: %s", f.name, e)

        return {"success": True, "snapshots": snapshots, "count": len(snapshots)}

    def restore_snapshot(self, snapshot_id: str) -> dict:
        """Restore session data from snapshot."""
        snapshot = Snapshot.load(snapshot_id)
        if not snapshot:
            return {"success": False, "error": f"snapshot not found: {snapshot_id}"}
        return {
            "success": True,
            "snapshot_id": snapshot_id,
            "session_id": snapshot.session_id,
            "label": snapshot.label,
            "created_at": snapshot.created_at,
            "data": snapshot.data.to_dict(),
        }

    def delete_snapshot(self, snapshot_id: str) -> dict:
        """Delete snapshot."""
        path = _SNAPSHOT_DIR / SNAPSHOT_PATH_TEMPLATE.format(snapshot_id=snapshot_id)
        if not path.exists():
            return {"success": False, "error": "snapshot not found"}
        try:
            path.unlink()
            return {"success": True, "snapshot_id": snapshot_id}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# 3. Global Singleton
# ══════════════════════════════════════════════════════════════════════

_manager: SessionExportManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> SessionExportManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SessionExportManager()
    return _manager


# ══════════════════════════════════════════════════════════════════════
# 4. API Handlers
# ══════════════════════════════════════════════════════════════════════


def handle_session_export(body: dict | None = None) -> dict:
    """POST /api/session/export — Export session"""
    b = body or {}
    return get_manager().export_session(
        session_id=b.get("session_id", ""),
        agent_id=b.get("agent_id", ""),
        messages=b.get("messages", []),
        tags=b.get("tags", []),
        metadata=b.get("metadata"),
    )


def handle_session_import(body: dict | None = None) -> dict:
    """POST /api/session/import — Import session"""
    b = body or {}
    raw = b.get("data", "")
    if not raw:
        return {"success": False, "error": "data (JSON string) required"}
    return get_manager().import_session(raw)


def handle_session_snapshots(body: dict | None = None) -> dict:
    """GET /api/session/snapshots — List snapshots"""
    return get_manager().list_snapshots()


def handle_session_snapshot_create(body: dict | None = None) -> dict:
    """POST /api/session/snapshot — Create snapshot"""
    b = body or {}
    return get_manager().create_snapshot(
        session_id=b.get("session_id", ""),
        messages=b.get("messages", []),
        agent_id=b.get("agent_id", ""),
        label=b.get("label", ""),
    )


def handle_session_snapshot_restore(body: dict | None = None) -> dict:
    """POST /api/session/snapshot/restore — Restore snapshot"""
    b = body or {}
    snapshot_id = b.get("snapshot_id", "")
    if not snapshot_id:
        return {"success": False, "error": "snapshot_id required"}
    return get_manager().restore_snapshot(snapshot_id)


def handle_session_snapshot_delete(body: dict | None = None) -> dict:
    """POST /api/session/snapshot/delete — Delete snapshot"""
    b = body or {}
    snapshot_id = b.get("snapshot_id", "")
    if not snapshot_id:
        return {"success": False, "error": "snapshot_id required"}
    return get_manager().delete_snapshot(snapshot_id)


# ── Route Registration ──

SESSION_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/session/export", handle_session_export, "Export session as JSON"),
    ("POST", "/api/session/import", handle_session_import, "Import session from JSON"),
    ("GET", "/api/session/snapshots", handle_session_snapshots, "List snapshots"),
    ("POST", "/api/session/snapshot", handle_session_snapshot_create, "Create snapshot"),
    ("POST", "/api/session/snapshot/restore", handle_session_snapshot_restore, "Restore snapshot"),
    ("POST", "/api/session/snapshot/delete", handle_session_snapshot_delete, "Delete snapshot"),
]
