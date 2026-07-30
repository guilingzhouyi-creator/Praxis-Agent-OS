"""Archive tool handlers and internal functions."""
from __future__ import annotations

import json
import sqlite3
import os
import time
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_500
from l1.kernel.paths import get_paths as _gp


_ARCHIVE_DB = os.environ.get("PRAXIS_ARCHIVE_DB", _gp().archive_db)
_db_conn: sqlite3.Connection | None = None


def _get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is not None:
        return _db_conn
    db_dir = os.path.dirname(_ARCHIVE_DB)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(_ARCHIVE_DB, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS archive (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        fonds       TEXT DEFAULT 'default',
        series      TEXT DEFAULT 'general',
        content     TEXT,
        tags        TEXT,
        title       TEXT DEFAULT '',
        ttl         REAL DEFAULT 0,
        created_at  REAL,
        updated_at  REAL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_created ON archive(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_fonds_series ON archive(fonds, series)")
    # Migrate existing databases: add columns if missing (idempotent)
    for col in ("title TEXT DEFAULT ''", "ttl REAL DEFAULT 0"):
        try:
            conn.execute(f"ALTER TABLE archive ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # column already exists
    _db_conn = conn
    return conn


def _cmd_archive_store(fonds: str, series: str, content: str, tags: str = "") -> dict:
    try:
        conn = _get_db()
        now = time.time()
        conn.execute(
            "INSERT INTO archive (fonds, series, content, tags, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (fonds, series, content, tags, now, now),
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def archive_store(args: dict, agent_id: str) -> dict:
    return _cmd_archive_store(
        fonds=args.get("fonds", "default"),
        series=args.get("series", "general"),
        content=args.get("content", ""),
        tags=args.get("tags", ""),
    )


def init_archive() -> dict:
    try:
        conn = _get_db()
        return {"success": True, "path": _ARCHIVE_DB}
    except Exception as e:
        return {"success": False, "error": str(e)}


def archive_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    fonds = args.get("fonds", "")
    series = args.get("series", "")
    limit = min(int(args.get("limit", 30)), 100)
    if not query and not fonds and not series:
        return {"success": False, "error": "query, fonds, or series required"}
    try:
        conn = _get_db()
        sql = "SELECT id, fonds, series, content, tags, created_at FROM archive WHERE 1=1"
        params: list[Any] = []
        if query:
            sql += " AND (content LIKE ? OR tags LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        if fonds:
            sql += " AND fonds = ?"
            params.append(fonds)
        if series:
            sql += " AND series = ?"
            params.append(series)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return {"success": True, "results": [{
            "id": r[0], "fonds": r[1], "series": r[2],
            "content": r[3][:LOG_TRUNC_500], "tags": r[4].split(",") if r[4] else [],
            "created_at": r[5],
        } for r in rows], "total": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}
