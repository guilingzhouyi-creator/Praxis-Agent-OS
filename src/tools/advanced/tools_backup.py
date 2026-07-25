"""Backup/restore tools - 4 kinds.

backup_create, backup_list, backup_restore, backup_delete
"""

import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

_backups: dict[str, dict] = {}


def _cmd_backup_create(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    name = args.get("name", f"backup-{int(time.time())}")
    if not path:
        return {"success": False, "error": "path is required"}
    src = Path(path)
    if not src.exists():
        return {"success": False, "error": f"path not found: {path}"}
    backup_id = str(uuid.uuid4())[:8]
    backup_dir = Path(f".backups/{backup_id}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        if src.is_dir():
            dst = backup_dir / src.name
            shutil.copytree(src, dst)
            size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
        else:
            dst = backup_dir / src.name
            shutil.copy2(src, dst)
            size = dst.stat().st_size
        _backups[backup_id] = {
            "id": backup_id, "name": name, "source": str(src), "path": str(dst),
            "size": size, "created_at": time.time(), "agent_id": agent_id,
        }
        return {"success": True, "data": {"backup_id": backup_id, "name": name, "size": size, "path": str(dst)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_backup_list(args: dict, agent_id: str) -> dict:
    items = sorted(_backups.values(), key=lambda x: -x["created_at"])
    return {"success": True, "data": {"backups": items, "count": len(items)}}


def _cmd_backup_restore(args: dict, agent_id: str) -> dict:
    backup_id = args.get("backup_id", "")
    if not backup_id or backup_id not in _backups:
        return {"success": False, "error": "invalid backup_id"}
    entry = _backups[backup_id]
    src = Path(entry["path"])
    dst = Path(entry["source"])
    if not src.exists():
        return {"success": False, "error": f"backup data not found: {entry['path']}"}
    try:
        if dst.exists():
            backup_old = Path(f"{dst}.before-restore")
            shutil.move(str(dst), str(backup_old))
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"success": True, "data": {"backup_id": backup_id, "restored_to": entry["source"], "name": entry["name"]}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_backup_delete(args: dict, agent_id: str) -> dict:
    backup_id = args.get("backup_id", "")
    if not backup_id or backup_id not in _backups:
        return {"success": False, "error": "invalid backup_id"}
    entry = _backups.pop(backup_id)
    try:
        path = Path(entry["path"])
        if path.exists():
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    except Exception as e:
            logger.warning("tools_backup: %s", e)
    return {"success": True, "data": {"backup_id": backup_id, "deleted": True}}


def register_tools() -> None:
    register(ToolSpec(name="backup_create", description="Create file/directory backup", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("name", "string", default="")],
                      handler=_cmd_backup_create))
    register(ToolSpec(name="backup_list", description="List all backups", category="generic", ring=R.RING_1, danger=0, handler=_cmd_backup_list))
    register(ToolSpec(name="backup_restore", description="Restore from backup", category="generic", ring=R.RING_2_5, danger=3,
                      parameters=[ParamSpec("backup_id", "string", required=True)],
                      handler=_cmd_backup_restore))
    register(ToolSpec(name="backup_delete", description="Delete backup", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("backup_id", "string", required=True)],
                      handler=_cmd_backup_delete))