"""Kernel event sourcing — append-only event store + replay across restarts.

Replaces the old snapshot-overwrite model with an append-only SQLite event log.
Events are immutable; full replay reconstructs kernel state from scratch.

Schema:
  events(
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    event    TEXT NOT NULL,
    payload  TEXT NOT NULL,   -- JSON
    ts       REAL NOT NULL   -- time.time()
  )

Usage:
  from kernel.persist import append, replay, snapshot, restore

  append("process.spawn", {"pid": 1, "name": "agent"})
  state = replay()  # reconstruct full kernel state
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

from .params import PERSIST_PATH, PERSIST_AUTO, PERSIST_INTERVAL, PERSIST_QUERY_LIMIT, PERSIST_EXPORT_LIMIT, PERSIST_EXPORT_INTERRUPT_LIMIT, PRAXIS_EVENTS_DB

logger = logging.getLogger(__name__)

_DB: sqlite3.Connection | None = None
_DB_LOCK = threading.Lock()
_DB_PATH: str = ""


def _db_path() -> str:
    global _DB_PATH
    if not _DB_PATH:
        _DB_PATH = PRAXIS_EVENTS_DB
    return _DB_PATH


def _get_db() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                path = _db_path()
                _DB = sqlite3.connect(path, check_same_thread=False)
                _DB.execute("PRAGMA journal_mode=WAL")
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


# ── Append ──

def append(event: str, payload: dict | None = None) -> int:
    """Append an immutable event to the store. Returns sequence number."""
    db = _get_db()
    with _DB_LOCK:
        cur = db.execute(
            "INSERT INTO events (event, payload, ts) VALUES (?, ?, ?)",
            (event, json.dumps(payload or {}, default=str), time.time()),
        )
        db.commit()
        return cur.lastrowid


def append_many(events: list[tuple[str, dict]]) -> list[int]:
    """Append multiple events atomically. Returns list of sequence numbers."""
    db = _get_db()
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

def query(event_type: str = "", after_seq: int = 0,
          limit: int = PERSIST_QUERY_LIMIT) -> list[dict]:
    """Query events. Returns list of {seq, event, payload, ts}."""
    db = _get_db()
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
    return [
        {"seq": r[0], "event": r[1], "payload": json.loads(r[2]), "ts": r[3]}
        for r in rows
    ]


def count(event_type: str = "") -> int:
    db = _get_db()
    with _DB_LOCK:
        if event_type:
            return db.execute("SELECT COUNT(*) FROM events WHERE event = ?", (event_type,)).fetchone()[0]
        return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def last_seq() -> int:
    db = _get_db()
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
    import kernel.process as proc
    import kernel.__init__ as kinit
    import kernel.device as dev
    from kernel.interrupt import get_table as int_table, InterruptType

    stats = {"events": 0, "processes": 0, "audit": 0, "devices": 0, "interrupts": 0}

    db = _get_db()
    with _DB_LOCK:
        rows = db.execute(
            "SELECT seq, event, payload, ts FROM events ORDER BY seq"
        ).fetchall()

    for row in rows:
        event, raw_payload = row[1], row[2]
        try:
            payload = json.loads(raw_payload)
        except Exception:
            continue
        stats["events"] += 1

        if event == "process.spawn":
            proc.get_table().spawn(
                payload.get("name", "?"), payload.get("role", ""),
                payload.get("parent_pid", 0), payload.get("ring", 1),
            )
            stats["processes"] += 1
        elif event == "process.exit":
            pt = proc.get_table()
            p = pt.get(payload.get("pid", 0))
            if p:
                from kernel.process import ProcessState
                pt.set_state(payload["pid"], ProcessState.ZOMBIE)
        elif event == "audit.record":
            kinit.record_audit(
                payload.get("op", ""), payload.get("agent_id", ""),
                payload.get("success", True),
                detail=payload.get("detail", ""),
            )
            stats["audit"] += 1
        elif event == "device.register":
            from .device import DeviceType
            try:
                dtype = DeviceType[payload["type"]]
                dev.get_device_manager().register(
                    payload["name"], dtype, payload.get("rate_limit", 10),
                    description=payload.get("description", ""),
                )
                stats["devices"] += 1
            except Exception as e:
                logger.warning("persist restore: %s", e)
        elif event == "interrupt.fire":
            try:
                it = int_table()
                itype = InterruptType[payload["type"]]
                it.fire(itype, agent_id=payload.get("agent_id", ""),
                        reason=payload.get("reason", ""))
                stats["interrupts"] += 1
            except Exception as e:
                logger.warning("persist restore: %s", e)

    return stats


# ── Snapshot (backward compat — saves to JSON too) ──

def save() -> dict:
    """Snapshot current kernel state to JSON (legacy path). Also appends events."""
    import kernel.process as proc
    import kernel.__init__ as kinit
    import kernel.interrupt as interr
    import kernel.device as dev

    # Append audit snapshot events
    for e in kinit.get_audit_log(limit=PERSIST_EXPORT_LIMIT):
        append("audit.record", {
            "op": e.get("op", ""), "agent_id": e.get("agent_id", ""),
            "success": e.get("success", True), "detail": e.get("detail", ""),
        })

    state = {
        "version": 2,
        "saved_at": time.time(),
        "event_count": count(),
        "process_table": proc.get_table().list(),
        "audit_log": kinit.get_audit_log(limit=PERSIST_EXPORT_LIMIT),
        "interrupt_counts": interr.get_table().counts(),
        "interrupt_recent": interr.get_table().recent(limit=PERSIST_EXPORT_INTERRUPT_LIMIT),
        "devices": dev.get_device_manager().list(),
    }
    try:
        tmp = PERSIST_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, PERSIST_PATH)
        return {"success": True, "path": PERSIST_PATH, "size": len(json.dumps(state)),
                "event_count": state["event_count"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def restore() -> dict:
    """Restore kernel state from snapshot (legacy path) OR replay events.

    Tries event replay first (richer), falls back to JSON snapshot.
    """
    # Prefer event replay
    try:
        s = replay()
        if s["events"] > 0:
            logger.info("replayed %d events: %s", s["events"], s)
            return {"success": True, "source": "event_store", **s}
    except Exception as e:
        logger.warning("event replay failed: %s", e)

    # Fallback: legacy JSON snapshot
    if not os.path.exists(PERSIST_PATH):
        return {"success": False, "error": "no state file"}
    try:
        with open(PERSIST_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        return {"success": False, "error": f"read failed: {e}"}

    import kernel.process as proc
    import kernel.__init__ as kinit
    import kernel.interrupt as interr
    import kernel.device as dev

    results = {}
    pt = proc.get_table()
    for p in state.get("process_table", []):
        if p.get("pid", 0) == 0:
            continue
        pt.spawn(p.get("name", "?"), p.get("role", ""), p.get("parent_pid", 0), p.get("ring", 1))
    results["processes"] = len(state.get("process_table", []))

    dm = dev.get_device_manager()
    for d in state.get("devices", []):
        from .device import DeviceType
        try:
            dtype = DeviceType[d["type"]]
            dm.register(d["name"], dtype, d.get("rate_limit", 10), description=d.get("description", ""))
        except Exception as e:
            logger.warning("persist restore: %s", e)
    results["devices"] = len(state.get("devices", []))

    return {"success": True, "source": "snapshot", **results}


def clear() -> bool:
    """Delete persistence files."""
    global _DB
    with _DB_LOCK:
        if _DB:
            try:
                _DB.close()
            except Exception as e:
                logger.warning("persist restore: %s", e)
            _DB = None
    ok = True
    for path in [PERSIST_PATH, _db_path()]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            ok = False
    return ok
