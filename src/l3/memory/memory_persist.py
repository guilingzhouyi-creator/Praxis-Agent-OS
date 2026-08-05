"""MemoryPersistMixin — Ring 2/3 persistence for MemoryManager.

Extracted from memory.py (P2 split).  ``MemEntry`` is imported lazily from
the parent module to avoid a circular import.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from l1.kernel.params.system import MEMORY_IMPORTANCE_BASE, MEMORY_PERSIST_FILE_RING3

logger = logging.getLogger(__name__)


class MemoryPersistMixin:
    """MemoryPersistMixin — JSONL (Ring 2) + SQLite FTS5 (Ring 3) persistence."""

    def _jsonl_path(self) -> Path:
        from l1.kernel.params.system import MEMORY_PERSIST_FILE_RING2
        from l1.kernel.paths import get_paths as _gp
        return (self._persist_dir or Path(_gp().data_dir)) / MEMORY_PERSIST_FILE_RING2

    def _ring3_path(self) -> Path:
        from l1.kernel.params.system import MEMORY_PERSIST_FILE_RING3
        from l1.kernel.paths import get_paths as _gp
        return (self._persist_dir or Path(_gp().data_dir)) / MEMORY_PERSIST_FILE_RING3

    def _ensure_ring3_db(self) -> None:
        """Create Ring 3 SQLite table with FTS5 if not exists."""
        import sqlite3
        import tempfile

        from l1.kernel.params.system import MEMORY_PERSIST_FILE_RING3
        data_dir = str(self._persist_dir) if self._persist_dir else tempfile.gettempdir()
        db_path = Path(data_dir) / MEMORY_PERSIST_FILE_RING3
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id      TEXT PRIMARY KEY,
                agent   TEXT NOT NULL,
                type    TEXT NOT NULL,
                content TEXT NOT NULL,
                tags    TEXT NOT NULL DEFAULT '',
                importance REAL DEFAULT 0.5,
                ts      REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
            USING fts5(content, tags, content=knowledge, content_rowid=rowid)
        """)
        conn.commit()
        conn.close()

    def persist(self, path: str | None = None) -> dict:
        """Persist dirty Ring 2 entries → JSONL, Ring 3 → SQLite FTS5.

        Only entries marked as dirty since the last persist are written.
        """
        p = Path(path) if path else self._persist_dir
        if not p:
            return {"success": False, "error": "no path configured"}
        p.mkdir(parents=True, exist_ok=True)
        self._persist_dir = p

        short_written = 0
        long_written = 0

        # Snapshot dirty sets under lock — do NOT clear them yet: entries are
        # only dropped after their writes succeed, so a failed persist leaves
        # the dirty set intact for retry (crash safety).
        with self._lock:
            dirty_short_ids = set(self._dirty_short)
            dirty_long_ids = set(self._dirty_long)

        # Ring 2 → JSONL (append-only, dirty entries only)
        if dirty_short_ids:
            jsonl_path = self._jsonl_path()
            all_short = self.short.to_dict()
            dirty_entries = [e for e in all_short if e["id"] in dirty_short_ids]
            if dirty_entries:
                with open(jsonl_path, "a", encoding="utf-8") as f:
                    for e in dirty_entries:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
                short_written = len(dirty_entries)
                with self._lock:
                    self._dirty_short.difference_update(dirty_short_ids)

        # Ring 3 → SQLite FTS5 (dirty entries only)
        if dirty_long_ids:
            import sqlite3
            self._ensure_ring3_db()
            db_path = Path(self._persist_dir) / MEMORY_PERSIST_FILE_RING3
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            all_long = self.long.to_dict()
            dirty_entries = [e for e in all_long if e["id"] in dirty_long_ids]
            for e in dirty_entries:
                cur = conn.execute(
                    "INSERT OR REPLACE INTO knowledge (id, agent, type, content, tags, importance, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (e["id"], e["agent_id"], e["entry_type"], e["content"],
                     ",".join(e.get("tags", [])), e.get("importance", MEMORY_IMPORTANCE_BASE), e.get("timestamp", time.time())),
                )
                # Sync FTS5 index for searchable content
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO knowledge_fts(rowid, content, tags) VALUES (?, ?, ?)",
                        (cur.lastrowid, e["content"], ",".join(e.get("tags", []))),
                    )
                except Exception:
                    logger.debug("memory: fts update failed")
            conn.commit()
            conn.close()
            long_written = len(dirty_entries)
            if dirty_entries:
                with self._lock:
                    self._dirty_long.difference_update(dirty_long_ids)

        return {"success": True, "short_written": short_written, "long_written": long_written}

    def restore(self, path: str | None = None,
                ring2_limit: int = 0, ring3_limit: int = 0) -> dict:
        """Restore Ring 2 from JSONL, Ring 3 from SQLite FTS5.

        Args:
            path: Persist directory. Defaults to configured path.
            ring2_limit: Max JSONL lines to restore (0 = unlimited).
            ring3_limit: Max SQLite rows to restore (0 = unlimited).
        """
        from l3.memory.memory import MemEntry
        p = Path(path) if path else self._persist_dir
        if not p:
            return {"success": False, "error": "no path configured"}
        self._persist_dir = p
        total = 0

        # Ring 2 ← JSONL
        jsonl_path = self._jsonl_path()
        if jsonl_path.exists():
            with open(jsonl_path, encoding="utf-8") as f:
                lines = f.readlines()
            before = len(lines)
            if ring2_limit > 0 and len(lines) > ring2_limit:
                lines = lines[-ring2_limit:]
                logger.warning("memory restore ring2: truncated %d→%d lines", before, len(lines))
            for line in lines:
                try:
                    data = json.loads(line)
                    self.short.push(MemEntry(**data))
                    total += 1
                except Exception as e:
                    logger.warning("services/memory: %s", e)

        # Ring 3 ← SQLite FTS5
        import tempfile

        from l1.kernel.params.system import MEMORY_PERSIST_FILE_RING3
        data_dir = str(self._persist_dir) if self._persist_dir else tempfile.gettempdir()
        db_path = Path(data_dir) / MEMORY_PERSIST_FILE_RING3
        if db_path.exists():
            import sqlite3
            try:
                conn = sqlite3.connect(str(db_path), check_same_thread=False)
                sql = "SELECT id, agent, type, content, tags, importance, ts FROM knowledge ORDER BY ts DESC"
                if ring3_limit > 0:
                    sql += f" LIMIT {ring3_limit}"
                rows = conn.execute(sql).fetchall()
                conn.close()
                before = len(rows)
                if ring3_limit > 0 and before > ring3_limit:
                    logger.warning("memory restore ring3: truncated %d→%d rows", before, ring3_limit)
                for row in rows:
                    entry = MemEntry(
                        id=row[0], agent_id=row[1], entry_type=row[2], content=row[3],
                        tags=row[4].split(",") if row[4] else [],
                        importance=row[5], timestamp=row[6],
                    )
                    self.long.push(entry)
                    total += 1
            except Exception as e:
                logger.warning("services/memory: %s", e)

        return {"success": True, "restored": total}
