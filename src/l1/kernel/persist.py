"""Kernel event sourcing — append-only event store + replay across restarts.

Replaces the old snapshot-overwrite model with an append-only SQLite event log.
Events are immutable; full replay reconstructs kernel state from scratch.

Architecture:
  Write connection:  single WAL-mode connection (serialized via _DB_LOCK)
  Read connections:  pool of 2 connections (parallel reads, share _DB_LOCK)

Schema:
  events(
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    event    TEXT NOT NULL,
    payload  TEXT NOT NULL,   -- JSON
    ts       REAL NOT NULL   -- time.time()
  )

Usage:
  from l1.kernel.persist import append, replay, snapshot, restore

  append("process.spawn", {"pid": 1, "name": "agent"})
  state = replay()  # reconstruct full kernel state
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from .params.system import (
    PERSIST_EXPORT_LIMIT,
    PERSIST_QUERY_LIMIT,
)
from .paths import get_paths as _gp

logger = logging.getLogger(__name__)

_DB: sqlite3.Connection | None = None  # write connection
_READ_DBS: list[sqlite3.Connection] = []  # read connection pool (2)
_READ_IDX: int = 0  # round-robin index
_DB_LOCK = threading.Lock()
_DB_PATH: str = ""


def _db_path() -> str:
    global _DB_PATH
    if not _DB_PATH:
        _DB_PATH = _gp().events_db
    return _DB_PATH


def _get_write_db() -> sqlite3.Connection:
    """Get or create the write connection (WAL mode, single writer)."""
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                path = _db_path()
                _DB = sqlite3.connect(path, check_same_thread=False)
                _DB.execute("PRAGMA journal_mode=WAL")
                _DB.execute("PRAGMA synchronous=NORMAL")
                _DB.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        "seq"    INTEGER PRIMARY KEY AUTOINCREMENT,
                        event    TEXT NOT NULL,
                        payload  TEXT NOT NULL,
                        ts       REAL NOT NULL
                    )
                """)
                _DB.execute("CREATE INDEX IF NOT EXISTS idx_events_event ON events(event)")
                _DB.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
                _DB.commit()
    return _DB


def _get_read_db() -> sqlite3.Connection:
    """Get or lazily create a read connection from the pool (round-robin)."""
    global _READ_DBS, _READ_IDX
    with _DB_LOCK:
        if not _READ_DBS:
            path = _db_path()
            for _ in range(2):
                conn = sqlite3.connect(path, check_same_thread=False)
                conn.execute("PRAGMA query_only=ON")
                _READ_DBS.append(conn)
        idx = _READ_IDX
        _READ_IDX = (idx + 1) % len(_READ_DBS)
        return _READ_DBS[idx]


# ── Append ──


def append(event: str, payload: dict | None = None) -> int:
    """Append an immutable event to the store. Returns sequence number."""
    db = _get_write_db()
    with _DB_LOCK:
        cur = db.execute(
            "INSERT INTO events (event, payload, ts) VALUES (?, ?, ?)",
            (event, json.dumps(payload or {}, default=str), time.time()),
        )
        db.commit()
        return cur.lastrowid


def append_many(events: list[tuple[str, dict]]) -> list[int]:
    """Append multiple events atomically. Returns list of sequence numbers."""
    db = _get_write_db()
    seqs = []
    with _DB_LOCK:
        for event, payload in events:
            cur = db.execute(
                "INSERT INTO events (event, payload, ts) VALUES (?, ?, ?)",
                (event, json.dumps(payload or {}, default=str), time.time()),
            )
            seqs.append(cur.lastrowid)
        db.commit()
    return seqs


# ── Query ──


def query(event_type: str = "", after_seq: int = 0, limit: int = PERSIST_QUERY_LIMIT) -> list[dict]:
    """Query events. Returns list of {seq, event, payload, ts}."""
    db = _get_read_db()
    with _DB_LOCK:
        if event_type:
            rows = db.execute(
                "SELECT seq, event, payload, ts FROM events WHERE event = ? AND seq > ? ORDER BY seq LIMIT ?",
                (event_type, after_seq, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT seq, event, payload, ts FROM events WHERE seq > ? ORDER BY seq LIMIT ?",
                (after_seq, limit),
            ).fetchall()
    return [{"seq": r[0], "event": r[1], "payload": json.loads(r[2]), "ts": r[3]} for r in rows]


def count(event_type: str = "") -> int:
    db = _get_read_db()
    with _DB_LOCK:
        if event_type:
            return db.execute("SELECT COUNT(*) FROM events WHERE event = ?", (event_type,)).fetchone()[0]
        return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def last_seq() -> int:
    db = _get_read_db()
    with _DB_LOCK:
        r = db.execute("SELECT MAX(seq) FROM events").fetchone()
        return r[0] or 0


# ── Replay ──


def replay() -> dict:
    """Replay ALL events to reconstruct kernel state.

    This is the invert of snapshot-based restore().  Returns stats.
    Each event type maps to a handler that mutates kernel state.
    Cannot be used if kernel is already loaded (call before init).
    """
    import l1.kernel.__init__ as kinit
    import l1.kernel.device as dev
    import l1.kernel.process as proc
    from l1.kernel.interrupt import InterruptType
    from l1.kernel.interrupt import get_table as int_table

    stats = {"events": 0, "processes": 0, "audit": 0, "devices": 0, "interrupts": 0}

    db = _get_read_db()
    with _DB_LOCK:
        rows = db.execute("SELECT seq, event, payload, ts FROM events ORDER BY seq").fetchall()

    for row in rows:
        event, raw_payload = row[1], row[2]
        try:
            payload = json.loads(raw_payload)
        except Exception:
            continue
        stats["events"] += 1

        if event == "process.spawn":
            proc.get_table().spawn(
                payload.get("name", "?"),
                payload.get("role", ""),
                payload.get("parent_pid", 0),
                payload.get("ring", 1),
            )
            stats["processes"] += 1
        elif event == "process.exit":
            pt = proc.get_table()
            p = pt.get(payload.get("pid", 0))
            if p:
                pt.exit(payload["pid"], exit_code=-1, reason="restored: process.exit")
        elif event == "audit.record":
            kinit.record_audit(
                payload.get("op", ""),
                payload.get("agent_id", ""),
                payload.get("success", True),
                detail=payload.get("detail", ""),
            )
            stats["audit"] += 1
        elif event == "device.register":
            from .device import DeviceType

            try:
                dtype = DeviceType[payload["type"]]
                dev.get_device_manager().register(
                    payload["name"],
                    dtype,
                    payload.get("rate_limit", 10),
                    description=payload.get("description", ""),
                )
                stats["devices"] += 1
            except Exception as e:
                logger.warning("persist restore: %s", e)
        elif event == "interrupt.fire":
            try:
                it = int_table()
                itype = InterruptType[payload["type"]]
                it.fire(itype, agent_id=payload.get("agent_id", ""), reason=payload.get("reason", ""))
                stats["interrupts"] += 1
            except Exception as e:
                logger.warning("persist restore: %s", e)

    return stats


# ── Snapshot (backward compat — saves to JSON too) ──


def save() -> dict:
    """Snapshot current kernel state via event sourcing (append-only)."""
    import l1.kernel.__init__ as kinit

    count = 0
    for e in kinit.get_audit_log(limit=PERSIST_EXPORT_LIMIT):
        append(
            "audit.record",
            {
                "op": e.get("op", ""),
                "agent_id": e.get("agent_id", ""),
                "success": e.get("success", True),
                "detail": e.get("detail", ""),
            },
        )
        count += 1
    return {"success": True, "events_appended": count}


def restore() -> dict:
    """Restore kernel state from event replay."""
    try:
        s = replay()
        return {"success": True, "source": "event_store", **s}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Backward-compatible accessor ──
