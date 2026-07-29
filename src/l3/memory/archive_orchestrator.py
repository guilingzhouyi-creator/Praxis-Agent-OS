"""ArchiveOrchestrator — bridges MemoryManager rings ↔ Archive catalog.

Part of the Four-Tier Hierarchical Memory Architecture:
  L0 Register → L1 Working → L2 Short-Term → L3 Long-Term → L4 Archive

Responsibilities:
  - shutdown: export Ring 3 entries (importance >= 0.7) to Archive fonds/series
  - boot:    restore recent Archive entries back into Ring 3 knowledge
  - classify: derive fonds/series from entry metadata
"""
from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import ARCHIVE_IMPORTANCE_THRESHOLD, ARCHIVE_RESTORE_LIMIT
from l1.kernel.params.system import LOG_TRUNC_2000

logger = logging.getLogger(__name__)


def archive_ring3(mem: Any) -> int:
    """Export Ring 3 entries with importance >= threshold to Archive.

    Called by shutdown_to_memories() during system shutdown.
    Each qualifying entry becomes an Archive entry under AGENT:{agent_id}/ entry_type.

    Returns:
        Number of entries archived.
    """
    from l3.tools._archive import _cmd_archive_store

    entries = mem.long.to_dict()
    count = 0
    for e in entries:
        if e.get("importance", 0) >= ARCHIVE_IMPORTANCE_THRESHOLD:
            fonds, series = _classify(e)
            r = _cmd_archive_store(
                fonds=fonds,
                series=series,
                content=e.get("content", ""),
                tags=",".join(str(t) for t in (e.get("tags") or [])),
            )
            if r.get("success"):
                count += 1
    if count > 0:
        logger.info("archive_orchestrator: archived %d Ring 3 entries", count)
    return count


def ring3_from_archive(mem: Any) -> int:
    """Restore recent Archive entries into Ring 3 knowledge.

    Called by boot.py:_init_services() during system startup.
    Restores the most recent ARCHIVE_RESTORE_LIMIT entries.

    Returns:
        Number of entries restored.
    """
    from l3.tools._archive import _get_db

    count = 0
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT fonds, series, content, tags, created_at FROM archive "
            "ORDER BY created_at DESC LIMIT ?",
            (ARCHIVE_RESTORE_LIMIT,),
        ).fetchall()
        for row in rows:
            fonds, series, content, tags_str, created_at = row
            agent_id = fonds.replace("AGENT:", "") if fonds.startswith("AGENT:") else "system"
            mem.remember(
                agent_id=agent_id or "system",
                entry_type="archive",
                content=f"[{fonds}/{series}] {content[:LOG_TRUNC_2000]}",
                tags=["archive", fonds, series] + ([t for t in tags_str.split(",") if t] if tags_str else []),
                ring=3,
                importance=ARCHIVE_IMPORTANCE_THRESHOLD,
            )
            count += 1
    except Exception as e:
        logger.warning("archive_orchestrator: ring3 restore failed: %s", e)
    if count > 0:
        logger.info("archive_orchestrator: restored %d entries from Archive to Ring 3", count)
    return count


def _classify(entry: dict) -> tuple[str, str]:
    """Derive fonds/series from MemoryManager entry metadata.

    Classification rules:
      - agent_id -> fonds (e.g. "agent-a" -> "AGENT:agent-a")
      - entry_type -> series (e.g. "tool_call" -> "tool_call")
      - Unknown entries fall back to "SYSTEM/general"
    """
    agent = entry.get("agent_id", "unknown") or "unknown"
    etype = entry.get("entry_type", "general") or "general"
    fonds = f"AGENT:{agent}"
    series = etype
    return fonds, series
