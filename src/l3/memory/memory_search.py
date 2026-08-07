"""Memory search — extracted from memory.py for modularity.

Contains MemoryManager.search_long_term() logic.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from l1.kernel.params.system import LOG_TRUNC_500, MEMORY_PERSIST_FILE_RING3

logger = logging.getLogger(__name__)


def search_long_term(mem, query: str, agent_id: str | None = None, limit: int = 10) -> list[dict]:
    """FTS5 full-text search across Ring 3 knowledge base."""
    data_dir = str(mem._persist_dir) if mem._persist_dir else tempfile.gettempdir()
    db_path = Path(data_dir) / MEMORY_PERSIST_FILE_RING3
    if not db_path.exists():
        return []
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        sql = """
            SELECT k.id, k.agent, k.type, k.content, k.tags, k.importance, k.ts
            FROM knowledge_fts f JOIN knowledge k ON f.rowid = k.rowid
            WHERE knowledge_fts MATCH ?
        """
        params = [query]
        if agent_id:
            sql += " AND k.agent = ?"
            params.append(agent_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(str(limit))
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [
            {"id": r[0], "agent_id": r[1], "entry_type": r[2], "content": r[3][:LOG_TRUNC_500],
             "tags": r[4].split(","), "importance": r[5], "timestamp": r[6]}
            for r in rows
        ]
    except Exception:
        return []
