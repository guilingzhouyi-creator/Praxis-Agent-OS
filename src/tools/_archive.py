"""Archive tool handlers and internal functions."""

import json
import sqlite3
import os

try:
    from services.archive_orchestrator import get_archiver
    HAS_ARCHIVE = True
except ImportError:
    HAS_ARCHIVE = False


from kernel.params import PRAXIS_ARCHIVE_DB as _ADB
_ARCHIVE_DB = os.environ.get("PRAXIS_ARCHIVE_DB", _ADB)


def _get_db() -> sqlite3.Connection:
    db_dir = os.path.dirname(_ARCHIVE_DB)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(_ARCHIVE_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS archive (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fonds TEXT DEFAULT 'default',
        series TEXT DEFAULT 'general',
        content TEXT, tags TEXT,
        created_at REAL, updated_at REAL
    )""")
    return conn


def _cmd_archive_store(fonds: str, series: str, content: str, tags: str = "") -> dict:
    try:
        conn = _get_db()
        now = __import__("time").time()
        conn.execute("INSERT INTO archive (fonds, series, content, tags, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                     (fonds, series, content, tags, now, now))
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
        conn.close()
        return {"success": True, "path": _ARCHIVE_DB}
    except Exception as e:
        return {"success": False, "error": str(e)}


def archive_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "query is required"}
    if not HAS_ARCHIVE:
        return {"success": False, "error": "archive not available"}
    try:
        archiver = get_archiver()
        results = archiver.search(query)
        return {"success": True, "results": results[:30], "total": len(results) if isinstance(results, list) else 0}
    except Exception as e:
        return {"success": False, "error": str(e)}
