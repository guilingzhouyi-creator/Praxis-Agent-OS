"""Workspace manager — project lifecycle, recent projects, workspace config."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from l1.kernel.params.system import PRAXIS_CONFIG_DIR, WORKSPACE_MAX_RECENT
from l1.kernel.platform import get_config_dir
CONFIG_DIR = Path(get_config_dir())
CONFIG_FILE = CONFIG_DIR / "workspaces.json"


def _ensure_config() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    _ensure_config()
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"recent": [], "workspaces": {}}


def _save(data: dict) -> None:
    _ensure_config()
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def open_path(path: str) -> dict:
    """Open a project path and add to recent list."""
    p = Path(path).resolve()
    if not p.is_dir():
        return {"success": False, "error": "directory not found"}
    data = _load()
    # Add/update recent
    recent = data.get("recent", [])
    recent = [r for r in recent if r.get("path") != str(p)]
    recent.insert(0, {"path": str(p), "name": p.name, "opened_at": time.time()})
    data["recent"] = recent[:WORKSPACE_MAX_RECENT]
    _save(data)
    return {"success": True, "path": str(p), "name": p.name}


def recent(max_count: int = 10) -> dict:
    data = _load()
    items = []
    for r in data.get("recent", [])[:max_count]:
        p = Path(r["path"])
        items.append({
            "path": r["path"],
            "name": r.get("name", p.name),
            "exists": p.exists(),
            "opened_at": r.get("opened_at", 0),
        })
    return {"success": True, "recent": items, "count": len(items)}


def get_config(path: str) -> dict:
    data = _load()
    ws = data.get("workspaces", {}).get(path, {})
    return {"success": True, "config": ws}


def set_config(path: str, config: dict) -> dict:
    data = _load()
    data.setdefault("workspaces", {})[path] = config
    _save(data)
    return {"success": True}


def remove(path: str) -> dict:
    data = _load()
    data["recent"] = [r for r in data.get("recent", []) if r.get("path") != path]
    data.get("workspaces", {}).pop(path, None)
    _save(data)
    return {"success": True}
