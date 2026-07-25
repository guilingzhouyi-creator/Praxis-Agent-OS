"""Memory与档案管理系统工具 — quick search/archive/catalog/organize.

L4: External Archive — SQLite-persistent, fonds/series/item hierarchical catalog.
Linked to MemoryManager Ring 3 via ArchiveOrchestrator (shutdown → archive, boot → restore).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_ARCHIVE_DB: str = ""  # set by init_archive()
_DB_LOCK = threading.Lock()


# ═════════════════════════════════════════════════════════════════════════════
# Data structures
# ═════════════════════════════════════════════════════════════════════════════

class ArchiveLevel:
    FONDS = "fonds"
    SERIES = "series"
    ITEM = "item"


@dataclass
class ArchiveEntry:
    entry_id: str = ""
    fonds: str = ""
    series: str = ""
    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    checksum: str = ""
    created_at: float = 0.0
    ttl: float = 0.0
    agent_id: str = ""
    level: str = ArchiveLevel.ITEM


# ═════════════════════════════════════════════════════════════════════════════
# SQLite backend
# ═════════════════════════════════════════════════════════════════════════════

def init_archive(db_dir: str = "") -> None:
    """Initialize the archive SQLite database. Creates tables on first call.

    Called by boot.py:_init_services() during startup.
    Safe to call multiple times (idempotent).
    """
    global _ARCHIVE_DB
    if not db_dir:
        db_dir = os.environ.get("PRAXIS_MEMORIES_DIR", os.path.join(os.getcwd(), "memories"))
    os.makedirs(db_dir, exist_ok=True)
    _ARCHIVE_DB = os.path.join(db_dir, "archive.db")
    with _DB_LOCK:
        conn = sqlite3.connect(_ARCHIVE_DB, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archive (
                id         TEXT PRIMARY KEY,
                fonds      TEXT NOT NULL,
                series     TEXT NOT NULL,
                title      TEXT NOT NULL,
                content    TEXT NOT NULL DEFAULT '',
                tags       TEXT NOT NULL DEFAULT '',
                checksum   TEXT NOT NULL DEFAULT '',
                agent_id   TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                ttl        REAL NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_archive_fonds_series
            ON archive(fonds, series)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_archive_tags
            ON archive(tags)
        """)
        conn.commit()
        conn.close()
    logger.info("archive initialized: %s", _ARCHIVE_DB)


def _get_db() -> sqlite3.Connection:
    if not _ARCHIVE_DB:
        init_archive()
    return sqlite3.connect(_ARCHIVE_DB, check_same_thread=False)


def count_entries() -> int:
    """Return total active entries in archive (used by DSL compiler for catalog.json)."""
    try:
        conn = _get_db()
        cur = conn.execute("SELECT COUNT(*) FROM archive WHERE (ttl = 0 OR created_at + ttl > ?)", (time.time(),))
        n = cur.fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _now() -> float:
    return time.time()


def _tags_to_str(tags: list[str]) -> str:
    return ",".join(tags)


def _str_to_tags(s: str) -> list[str]:
    return [t for t in s.split(",") if t]


def _row_to_dict(row: tuple) -> dict:
    """Convert a SQLite row to the dict format used by all _cmd_* functions."""
    return {
        "entry_id": row[0], "fonds": row[1], "series": row[2],
        "title": row[3], "content": row[4],
        "tags": _str_to_tags(row[5]), "checksum": row[6],
        "agent_id": row[7], "created_at": row[8], "ttl": row[9],
    }


# ═════════════════════════════════════════════════════════════════════════════
# Archive tools (API-compatible with the old in-memory version)
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_archive_store(args: dict, agent_id: str) -> dict:
    fonds = args.get("fonds", "default")
    series = args.get("series", "general")
    title = args.get("title", "")
    content = args.get("content", "")
    tags = args.get("tags", [])
    ttl = args.get("ttl", 0)
    if not title:
        return {"success": False, "error": "title is required"}
    eid = f"arch-{uuid.uuid4().hex[:8]}"
    now = _now()
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO archive (id, fonds, series, title, content, tags, checksum, agent_id, created_at, ttl) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, fonds, series, title, content, _tags_to_str(tags), _checksum(content), agent_id, now, ttl),
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e)}
    conn.close()
    return {"success": True, "data": {"entry_id": eid, "fonds": fonds, "series": series, "size": len(content)}}


def archive_store(fonds: str, series: str, title: str, content: str = "",
                  tags: list[str] | None = None, ttl: float = 0,
                  agent_id: str = "system") -> dict:
    """Public API: store an entry in the archive.

    Args:
        fonds: Top-level collection name (e.g. "CONVENTION:card-xxx")
        series: Sub-collection name (e.g. "deliberation")
        title: Entry title (required)
        content: Entry body text
        tags: List of tag strings
        ttl: Time-to-live in seconds (0 = permanent)
        agent_id: Source agent identifier

    Returns:
        {"success": True, "data": {"entry_id", "fonds", "series", "size"}}
    """
    return _cmd_archive_store({
        "fonds": fonds, "series": series, "title": title,
        "content": content, "tags": tags or [], "ttl": ttl,
    }, agent_id=agent_id)


def _cmd_archive_retrieve(args: dict, agent_id: str) -> dict:
    entry_id = args.get("entry_id", "")
    conn = _get_db()
    cur = conn.execute("SELECT * FROM archive WHERE id = ?", (entry_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"success": False, "error": "entry not found"}
    entry = _row_to_dict(row)
    if entry["ttl"] > 0 and _now() > entry["created_at"] + entry["ttl"]:
        # Expired — remove and report
        conn2 = _get_db()
        conn2.execute("DELETE FROM archive WHERE id = ?", (entry_id,))
        conn2.commit()
        conn2.close()
        return {"success": False, "error": "entry expired"}
    entry["content"] = entry["content"][:4096]
    return {"success": True, "data": entry}


def _cmd_archive_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    fonds = args.get("fonds", "")
    series = args.get("series", "")
    max_results = args.get("max_results", 20)
    if not query:
        return {"success": False, "error": "query is required"}
    params: list[Any] = [f"%{query}%"]
    sql = "SELECT * FROM archive WHERE (ttl = 0 OR created_at + ttl > ?) AND (title LIKE ? OR content LIKE ?)"
    time_param = time.time()
    params = [time_param, f"%{query}%", f"%{query}%"]
    if fonds:
        sql += " AND fonds = ?"
        params.append(fonds)
    if series:
        sql += " AND series = ?"
        params.append(series)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max_results)
    conn = _get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    results = []
    for row in rows:
        e = _row_to_dict(row)
        results.append({
            "entry_id": e["entry_id"], "title": e["title"],
            "fonds": e["fonds"], "series": e["series"],
            "tags": e["tags"], "snippet": e["content"][:200],
        })
    return {"success": True, "data": {"results": results, "count": len(results), "query": query}}


def _cmd_archive_tag_search(args: dict, agent_id: str) -> dict:
    tag = args.get("tag", "")
    if not tag:
        return {"success": False, "error": "tag is required"}
    now = _now()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM archive WHERE (ttl = 0 OR created_at + ttl > ?) AND tags LIKE ? ORDER BY created_at DESC",
        (now, f"%{tag}%"),
    ).fetchall()
    conn.close()
    results = [{"entry_id": r[0], "title": r[3], "fonds": r[1], "series": r[2]} for r in rows]
    return {"success": True, "data": {"tag": tag, "results": results, "count": len(results)}}


def _cmd_archive_fonds_search(args: dict, agent_id: str) -> dict:
    fonds = args.get("fonds", "")
    series = args.get("series", "")
    if not fonds:
        return {"success": False, "error": "fonds is required"}
    now = _now()
    conn = _get_db()
    if series:
        rows = conn.execute(
            "SELECT * FROM archive WHERE (ttl = 0 OR created_at + ttl > ?) AND fonds = ? AND series = ? ORDER BY created_at DESC",
            (now, fonds, series),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM archive WHERE (ttl = 0 OR created_at + ttl > ?) AND fonds = ? ORDER BY created_at DESC",
            (now, fonds),
        ).fetchall()
    conn.close()
    results = [{"entry_id": r[0], "title": r[3], "series": r[2]} for r in rows]
    return {"success": True, "data": {"fonds": fonds, "series": series or "*", "results": results, "count": len(results)}}


def _cmd_archive_catalog(args: dict, agent_id: str) -> dict:
    now = _now()
    conn = _get_db()
    rows = conn.execute(
        "SELECT fonds, series, COUNT(*) FROM archive WHERE (ttl = 0 OR created_at + ttl > ?) GROUP BY fonds, series ORDER BY fonds, series",
        (now,),
    ).fetchall()
    conn.close()
    catalog: dict[str, dict[str, int]] = {}
    for fonds, series, cnt in rows:
        catalog.setdefault(fonds, {})[series] = cnt
    total = sum(c for s in catalog.values() for c in s.values())
    return {"success": True, "data": {"catalog": catalog, "total_entries": total, "fonds_count": len(catalog)}}


def _cmd_archive_stats(args: dict, agent_id: str) -> dict:
    now = _now()
    conn = _get_db()
    cur = conn.execute("SELECT COUNT(*) FROM archive")
    total = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM archive WHERE ttl > 0 AND created_at + ttl < ?", (now,))
    expired = cur.fetchone()[0]
    cur = conn.execute("SELECT fonds, COUNT(*) FROM archive GROUP BY fonds")
    by_fonds = dict(cur.fetchall())
    conn.close()
    return {"success": True, "data": {
        "total": total, "active": total - expired, "expired": expired,
        "by_fonds": by_fonds,
    }}


def _cmd_archive_compact(args: dict, agent_id: str) -> dict:
    now = _now()
    conn = _get_db()
    cur = conn.execute("SELECT COUNT(*) FROM archive WHERE ttl > 0 AND created_at + ttl < ?", (now,))
    expired = cur.fetchone()[0]
    conn.execute("DELETE FROM archive WHERE ttl > 0 AND created_at + ttl < ?", (now,))
    conn.commit()
    cur = conn.execute("SELECT COUNT(*) FROM archive")
    remaining = cur.fetchone()[0]
    conn.close()
    return {"success": True, "data": {"removed": expired, "remaining": remaining}}


def _cmd_archive_reindex(args: dict, agent_id: str) -> dict:
    """Reindex is a no-op with SQLite (indexes auto-maintained).
    Kept for API compatibility."""
    conn = _get_db()
    cur = conn.execute("SELECT COUNT(*) FROM archive")
    total = cur.fetchone()[0]
    conn.close()
    return {"success": True, "data": {"reindexed": True, "entries": total}}


def _cmd_archive_export(args: dict, agent_id: str) -> dict:
    fonds_filter = args.get("fonds", "")
    now = _now()
    conn = _get_db()
    if fonds_filter:
        rows = conn.execute(
            "SELECT * FROM archive WHERE (ttl = 0 OR created_at + ttl > ?) AND fonds = ? ORDER BY created_at",
            (now, fonds_filter),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM archive WHERE (ttl = 0 OR created_at + ttl > ?) ORDER BY created_at",
            (now,),
        ).fetchall()
    conn.close()
    entries = [_row_to_dict(r) for r in rows]
    return {"success": True, "data": {"entries": entries, "count": len(entries), "format": "json"}}


# ═════════════════════════════════════════════════════════════════════════════
# Tool registry
# ═════════════════════════════════════════════════════════════════════════════

TOOLS = {
    "archive_store":       {"func": _cmd_archive_store,       "danger": 1},
    "archive_retrieve":    {"func": _cmd_archive_retrieve,    "danger": 0},
    "archive_search":      {"func": _cmd_archive_search,      "danger": 0},
    "archive_tag_search":  {"func": _cmd_archive_tag_search,  "danger": 0},
    "archive_fonds_search":{"func": _cmd_archive_fonds_search,"danger": 0},
    "archive_catalog":     {"func": _cmd_archive_catalog,     "danger": 0},
    "archive_stats":       {"func": _cmd_archive_stats,       "danger": 0},
    "archive_compact":     {"func": _cmd_archive_compact,     "danger": 1},
    "archive_reindex":     {"func": _cmd_archive_reindex,     "danger": 1},
    "archive_export":      {"func": _cmd_archive_export,      "danger": 0},
}


def execute_archive_tool(tool_name: str, args: dict, agent_id: str = "") -> dict:
    tool = TOOLS.get(tool_name)
    if not tool:
        return {"success": False, "error": f"unknown archive tool: {tool_name}"}
    try:
        return tool["func"](args, agent_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


def quick_recall(query: str, max_results: int = 5) -> list[dict]:
    result = _cmd_archive_search({"query": query, "max_results": max_results}, "")
    return result.get("data", {}).get("results", [])


def register_tools() -> None:
    from services.tool_spec import ToolSpec, ParamSpec, register, ToolRing as R
    register(ToolSpec(name="archive_store", description="Store entry in archive (fonds/series/item)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("fonds","string",default="default"), ParamSpec("series","string",default="general"),
                                  ParamSpec("title","string",required=True), ParamSpec("content","string",default=""),
                                  ParamSpec("tags","list",default=[]), ParamSpec("ttl","int",default=0)],
                      handler=_cmd_archive_store))
    register(ToolSpec(name="archive_retrieve", description="Retrieve archive entry", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("entry_id","string",required=True)], handler=_cmd_archive_retrieve))
    register(ToolSpec(name="archive_search", description="Search archive content", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("query","string",required=True), ParamSpec("fonds","string",default=""),
                                  ParamSpec("series","string",default=""), ParamSpec("max_results","int",default=20)],
                      handler=_cmd_archive_search))
    register(ToolSpec(name="archive_tag_search", description="Search by tag", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("tag","string",required=True)], handler=_cmd_archive_tag_search))
    register(ToolSpec(name="archive_fonds_search", description="Search by fonds/series", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("fonds","string",required=True), ParamSpec("series","string",default="")],
                      handler=_cmd_archive_fonds_search))
    register(ToolSpec(name="archive_catalog", description="List archive catalog", category="generic", ring=R.RING_1, danger=0, handler=_cmd_archive_catalog))
    register(ToolSpec(name="archive_stats", description="Archive statistics", category="generic", ring=R.RING_1, danger=0, handler=_cmd_archive_stats))
    register(ToolSpec(name="archive_compact", description="Compact expired entries", category="generic", ring=R.RING_2_5, danger=1, handler=_cmd_archive_compact))
    register(ToolSpec(name="archive_reindex", description="Rebuild archive index", category="generic", ring=R.RING_2_5, danger=1, handler=_cmd_archive_reindex))
    register(ToolSpec(name="archive_export", description="Export archive as JSON", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("fonds","string",default="")], handler=_cmd_archive_export))
