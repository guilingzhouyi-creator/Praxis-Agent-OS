"""Archive tool handlers and internal functions."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_500
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)

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
        ref_code    TEXT DEFAULT '',
        created_at  REAL,
        updated_at  REAL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_created ON archive(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_fonds_series ON archive(fonds, series)")
    # Migrate existing databases: add columns if missing (idempotent)
    for col in ("title TEXT DEFAULT ''", "ttl REAL DEFAULT 0",
                "ref_code TEXT DEFAULT ''"):
        try:
            conn.execute(f"ALTER TABLE archive ADD COLUMN {col}")
        except sqlite3.OperationalError:
            logger.debug("archive: column already exists, skipping migration")
    _db_conn = conn
    return conn


def _normalize_fonds(fonds: str) -> str:
    """Normalize a fonds name: lowercase, trimmed, code-safe.

    Ensures ``agent-a`` and ``agent-A`` address the same fonds.
    """
    return re.sub(r"[^a-z0-9_-]+", "-", (fonds or "default").strip().lower())


def _purge_expired() -> int:
    """Delete records whose ttl has lapsed (ttl > 0 and created_at + ttl < now)."""
    try:
        conn = _get_db()
        now = time.time()
        cur = conn.execute(
            "DELETE FROM archive WHERE ttl > 0 AND created_at + ttl < ?", (now,))
        conn.commit()
        if cur.rowcount:
            logger.info("archive: purged %d expired records", cur.rowcount)
        return cur.rowcount
    except Exception as e:
        logger.warning("archive: purge expired failed: %s", e)
        return 0


def _next_ref_code(conn: sqlite3.Connection, fonds: str, series: str) -> str:
    """Build a record number: fonds_code-series_code-seq (Chinese archive style)."""
    fonds_code = re.sub(r"[^a-z0-9]", "", fonds)[:8] or "default"
    series_code = re.sub(r"[^a-z0-9]", "", series)[:6] or "general"
    row = conn.execute(
        "SELECT COUNT(*) FROM archive WHERE fonds = ? AND series = ?",
        (fonds, series)).fetchone()
    seq = (row[0] if row else 0) + 1
    return f"{fonds_code}-{series_code}-{seq:05d}"


def _cmd_archive_store(fonds: str, series: str, content: str, tags: str = "") -> dict:
    try:
        conn = _get_db()
        _purge_expired()
        fonds = _normalize_fonds(fonds)
        now = time.time()
        ref_code = _next_ref_code(conn, fonds, series)
        conn.execute(
            "INSERT INTO archive (fonds, series, content, tags, created_at, updated_at, ref_code)"
            " VALUES (?,?,?,?,?,?,?)",
            (fonds, series, content, tags, now, now, ref_code),
        )
        conn.commit()
        return {"success": True, "ref_code": ref_code}
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
        _purge_expired()
        sql = "SELECT id, fonds, series, content, tags, created_at, ref_code FROM archive WHERE 1=1"
        params: list[Any] = []
        if query:
            sql += " AND (content LIKE ? OR tags LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        if fonds:
            sql += " AND fonds = ?"
            params.append(_normalize_fonds(fonds))
        if series:
            sql += " AND series = ?"
            params.append(series)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return {"success": True, "results": [{
            "id": r[0], "fonds": r[1], "series": r[2],
            "content": r[3][:LOG_TRUNC_500], "tags": r[4].split(",") if r[4] else [],
            "created_at": r[5], "ref_code": r[6],
        } for r in rows], "total": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}
