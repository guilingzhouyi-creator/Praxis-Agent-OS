"""L3B Message Cache Pool — Ring buffer for inter-composite messages + persistent dynamic expansion.

In the L3B bus architecture:
  Each L3B composite has a message cache pool used to temporarily hold pending messages.
  The message cache pool has two layers:
    - Hot Ring: in-memory deque, latest N messages, ring eviction
    - Persist Queue: SQLite persistence, automatically demotes storage when Hot Ring is full

Auto-scaling strategy:
  Hot Ring usage ≥ 80% → enable persist queue
  Persist queue backlog ≥ threshold → send BACKPRESSURE signal to upstream composite
  Backpressure resolved → refill from persist queue back to hot ring
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l1.kernel.params.system import (
    L3B_BACKPRESSURE_COOLDOWN,
    L3B_BACKPRESSURE_THRESHOLD,
    L3B_HOT_RING_SIZE,
    L3B_MESSAGE_DB,
    L3B_MESSAGE_DIR,
    L3B_PERSIST_HIGH_WATERMARK,
)
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)


@dataclass
class CacheMessage:
    """CacheMessage — cache message record (msg_id, msg_type, sender, target, payload)."""
    msg_id: str
    msg_type: str
    sender: str
    target: str
    payload: str                  # JSON-serialized message body
    timestamp: float
    priority: int = 5
    delivered: bool = False


class L3BMessagePool:
    """Message cache pool for an L3B composite.

    Each composite has its own independent instance.
    Supports hot ring buffer + persist queue + dynamic scaling.
    """

    def __init__(
        self,
        composite_id: str,
        hot_size: int = L3B_HOT_RING_SIZE,
        persist_dir: str = "",
        high_watermark: float = L3B_PERSIST_HIGH_WATERMARK,
        bp_threshold: int = L3B_BACKPRESSURE_THRESHOLD,
    ):
        self.composite_id = composite_id
        self._hot_size = hot_size
        self._high_watermark = high_watermark
        self._bp_threshold = bp_threshold
        self._bp_cooldown = L3B_BACKPRESSURE_COOLDOWN
        self._hot: deque[CacheMessage] = deque(maxlen=hot_size)        # Hot Ring
        self._lock = threading.Lock()
        self._total_pushed = 0
        self._total_popped = 0
        self._last_bp_time = 0.0

        # Persist directory
        _msg_dir = os.path.join(_gp().data_dir, L3B_MESSAGE_DIR)
        persist_dir = persist_dir or os.path.join(_msg_dir, composite_id.replace("-", "_"))
        self._persist_path = Path(persist_dir)
        self._persist_path.mkdir(parents=True, exist_ok=True)
        self._db_path = os.path.join(_msg_dir, L3B_MESSAGE_DB)
        self._init_db()

    # ── Persist Initialization ──

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "  id TEXT PRIMARY KEY,"
            "  msg_type TEXT NOT NULL,"
            "  sender TEXT NOT NULL,"
            "  target TEXT NOT NULL,"
            "  payload TEXT DEFAULT '',"
            "  timestamp REAL NOT NULL,"
            "  priority INTEGER DEFAULT 5,"
            "  delivered INTEGER DEFAULT 0"
            ")"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_undelivered ON messages(delivered, timestamp)")
        conn.commit()
        conn.close()

    # ── Write Path ──

    def push(self, msg_id: str, msg_type: str, sender: str, target: str,
             payload: Any = None, priority: int = 5) -> dict:
        """Write a message into the cache pool.

        First enters the Hot Ring (ring buffer).
        When Hot Ring usage ≥ watermark, also writes to the persist queue.
        """
        msg = CacheMessage(
            msg_id=msg_id,
            msg_type=msg_type,
            sender=sender,
            target=target,
            payload=json.dumps(payload) if payload is not None else "",
            timestamp=time.time(),
            priority=priority,
        )

        with self._lock:
            # Write to Hot Ring
            self._hot.append(msg)
            self._total_pushed += 1

            # Watermark check → persist
            usage = len(self._hot) / self._hot_size
            if usage >= self._high_watermark:
                self._persist_one(msg)
                logger.debug(
                    "L3BMessagePool %s: hot ring at %.0f%%, persisted msg %s",
                    self.composite_id, usage * 100, msg_id,
                )

        # Backpressure check (outside lock to avoid deadlock)
        if self._should_backpressure():
            return {"success": True, "backpressure": True}
        return {"success": True}

    # ── Read Path ──

    def pop(self, limit: int = 10, block: bool = False,
            timeout: float = 1.0) -> list[dict]:
        """Read messages from the cache pool.

        Reads from the Hot Ring first.
        If the Hot Ring is empty, restores from the persist queue.
        """
        with self._lock:
            results: list[CacheMessage] = []
            while len(results) < limit and self._hot:
                msg = self._hot.popleft()
                if msg.delivered:
                    continue
                msg.delivered = True
                results.append(msg)

            # If Hot Ring is insufficient, supplement from persist
            if len(results) < limit:
                restored = self._restore_from_db(limit - len(results))
                results.extend(restored)

            self._total_popped += len(results)

        return [self._to_dict(m) for m in results]

    def peek(self, limit: int = 10) -> list[dict]:
        """Non-destructive read."""
        with self._lock:
            results = list(self._hot)[:limit]
        return [self._to_dict(m) for m in results]

    # ── Status ──

    def hot_usage(self) -> float:
        """Return the hot ring usage ratio (0.0-1.0)."""
        with self._lock:
            return len(self._hot) / self._hot_size

    def persist_count(self) -> int:
        """Return the count of undelivered persisted messages."""
        conn = sqlite3.connect(self._db_path)
        cnt = conn.execute("SELECT COUNT(*) FROM messages WHERE delivered=0").fetchone()[0]
        conn.close()
        return cnt

    def stats(self) -> dict:
        """Return cache pool statistics. Returns a stats dict."""
        return {
            "composite_id": self.composite_id,
            "hot_usage": round(self.hot_usage() * 100, 1),
            "hot_size": len(self._hot),
            "hot_max": self._hot_size,
            "persist_count": self.persist_count(),
            "total_pushed": self._total_pushed,
            "total_popped": self._total_popped,
            "backpressure": self._should_backpressure(),
        }

    # ── Internal Methods ──

    def _persist_one(self, msg: CacheMessage) -> None:
        """Persist one message."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO messages "
                "(id, msg_type, sender, target, payload, timestamp, priority, delivered) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (msg.msg_id, msg.msg_type, msg.sender, msg.target,
                 msg.payload, msg.timestamp, msg.priority, 1 if msg.delivered else 0),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("L3BMessagePool persist: %s", e)

    def _restore_from_db(self, limit: int) -> list[CacheMessage]:
        """Restore undelivered messages from the persist queue back to Hot Ring."""
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT id, msg_type, sender, target, payload, timestamp, priority "
                "FROM messages WHERE delivered=0 ORDER BY timestamp ASC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
            results = []
            for row in rows:
                msg = CacheMessage(
                    msg_id=row[0], msg_type=row[1], sender=row[2],
                    target=row[3], payload=row[4], timestamp=row[5],
                    priority=row[6], delivered=True,
                )
                results.append(msg)
                # Mark as delivered
                conn2 = sqlite3.connect(self._db_path)
                conn2.execute("UPDATE messages SET delivered=1 WHERE id=?", (row[0],))
                conn2.commit()
                conn2.close()
            return results
        except Exception as e:
            logger.warning("L3BMessagePool restore: %s", e)
            return []

    def _should_backpressure(self) -> bool:
        """Determine whether to send a backpressure signal.

        Conditions:
          1. Persist queue backlog ≥ threshold
          2. Time since last backpressure exceeds cooldown period
        """
        now = time.time()
        if now - self._last_bp_time < self._bp_cooldown:
            return False
        pcount = self.persist_count()
        if pcount >= self._bp_threshold:
            self._last_bp_time = now
            hot_usage = self.hot_usage()
            logger.info(
                "L3BMessagePool %s: BACKPRESSURE (persist=%d, hot=%.0f%%)",
                self.composite_id, pcount, hot_usage * 100,
            )
            return True
        return False

    @staticmethod
    def _to_dict(msg: CacheMessage) -> dict:
        return {
            "msg_id": msg.msg_id,
            "msg_type": msg.msg_type,
            "sender": msg.sender,
            "target": msg.target,
            "payload": json.loads(msg.payload) if msg.payload else None,
            "timestamp": msg.timestamp,
            "priority": msg.priority,
        }

    def close(self) -> None:
        """Close the cache pool (clean up the persist directory)."""
        self._hot.clear()
        try:
            import shutil
            shutil.rmtree(str(self._persist_path), ignore_errors=True)
        except Exception:
            logger.debug("l3b_message_pool: persist dir cleanup failed")
        logger.info("L3BMessagePool %s: closed", self.composite_id)
