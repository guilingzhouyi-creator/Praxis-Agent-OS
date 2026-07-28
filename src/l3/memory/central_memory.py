"""CentralMemory — unified memory lifecycle coordinator.

Orchestrates the four-ring memory pyramid under a single API:
  Ring 1 (Working)    — 8K token budget, 30min TTL, in-memory
  Ring 2 (Short-term) — 32K token budget, 24h TTL, JSONL file
  Ring 3 (Long-term)  — 128K token budget, no TTL, SQLite FTS5
  Ring 4 (Archive)    — fonds/series/item, disk persistent

Coordinates memory_ring, memory_quality, memory_init, and r4_agent.
Provides unified remember, recall, compact, and archive operations.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CentralMemory:
    """Single entry point for all memory operations across all four rings."""

    def __init__(self):
        """Initialize the central memory coordinator with zeroed statistics."""
        self._stats: dict[str, int] = {"stores": 0, "recalls": 0, "compactions": 0, "archives": 0}

    def remember(self, agent_id: str, content: str, *,
                 entry_type: str = "observation",
                 tags: list[str] | None = None,
                 ring: int = 1,
                 importance: float = 0.5,
                 cell_id: str = "") -> dict:
        """Store an entry in the appropriate memory ring.

        Rings: 1=working, 2=short, 3=long, 4=archive.
        Quality gate is applied for Rings 1-3.
        Ring 4 goes directly to archive.
        cell_id: optional Cell partition key for per-Cell memory isolation.
        """
        tags = tags or []
        self._stats["stores"] += 1

        # Quality gate (Rings 1-3)
        if ring <= 3:
            try:
                from .memory_quality import _is_good_memory, _score_importance
                accepted, reason = _is_good_memory(content, entry_type)
                if not accepted:
                    return {"success": False, "ring": ring, "reason": f"quality_rejected:{reason}"}
                if importance == 0.5:
                    importance = _score_importance(content, entry_type)
            except Exception:
                pass

        if ring == 4:
            # Archive directly to fonds/series store
            try:
                from l3.tools._archive import _cmd_archive_store
                from .archive_orchestrator import _classify
                pseudo_entry = {
                    "agent_id": agent_id,
                    "entry_type": entry_type,
                    "content": content,
                    "tags": tags or [],
                }
                fonds, series = _classify(pseudo_entry)
                r = _cmd_archive_store(fonds=fonds, series=series,
                                       content=content,
                                       tags=",".join(tags or []))
                self._stats["archives"] += 1
                return {"success": True, "ring": 4, "result": r}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Rings 1-3 via memory module
        try:
            from .memory import get_memory
            mem = get_memory()
            r = mem.remember(agent_id=agent_id, entry_type=entry_type,
                             content=content, tags=tags, ring=ring,
                             cell_id=cell_id)
            return {"success": True, "ring": ring, "result": r}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def recall(self, agent_id: str = "", *,
               query: str = "", tags: list[str] | None = None,
               rings: list[int] | None = None,
               limit: int = 20) -> list[dict]:
        """Search across multiple memory rings.

        Returns entries ordered by relevance, newest first.
        """
        tags = tags or []
        rings = rings or [1, 2, 3, 4]
        self._stats["recalls"] += 1
        results = []

        try:
            from .memory import get_memory
            mem = get_memory()
            for ring in rings:
                try:
                    entries = mem.recall(agent_id=agent_id if agent_id else None,
                                         tag=tags[0] if tags else None,
                                         rings=[ring],
                                         limit=limit)
                    for e in (entries or []):
                        if isinstance(e, dict):
                            e["_ring"] = ring
                            results.append(e)
                        else:
                            # MemEntry dataclass → dict
                            results.append({
                                "id": e.id, "agent_id": e.agent_id,
                                "entry_type": e.entry_type, "content": e.content,
                                "tokens": e.tokens, "tags": list(e.tags),
                                "importance": e.importance,
                                "timestamp": e.timestamp, "ttl": e.ttl,
                                "_ring": ring,
                            })
                except Exception:
                    pass
        except Exception as e:
            logger.warning("central_memory recall: %s", e)

        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return results[:limit]

    def compact(self, agent_id: str = "", ring: int = 0) -> dict:
        """Trigger compaction on one or all rings."""
        self._stats["compactions"] += 1
        try:
            from .memory import get_memory
            mem = get_memory()
            if ring and ring <= 3:
                r = mem.compact(agent_id, ring=ring)
            else:
                r = mem.compact(agent_id)
            return {"success": True, "ring": ring or "all", "result": r}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def archive_ring3(self, mem_any: Any | None = None) -> dict:
        """Incremental archive from Ring 3 to Ring 4."""
        self._stats["archives"] += 1
        try:
            from .archive_orchestrator import archive_ring3
            n = archive_ring3(mem_any)
            return {"success": True, "archived": n}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stats(self) -> dict:
        """Return cumulative operation statistics across all rings."""
        base = dict(self._stats)
        try:
            from .memory import get_memory
            mem = get_memory()
            ms = mem.stats() if hasattr(mem, 'stats') else {}
            base["memory_stats"] = ms
        except Exception:
            pass
        try:
            from .r4_agent import get_r4_agent
            r4 = get_r4_agent()
            r4s = r4.stats() if hasattr(r4, 'stats') else {}
            base["r4_stats"] = r4s
        except Exception:
            pass
        return base


_center: CentralMemory | None = None


def get_center() -> CentralMemory:
    """Return the singleton CentralMemory instance, creating it if needed."""
    global _center
    if _center is None:
        _center = CentralMemory()
    return _center


def reset_center() -> None:
    """Reset the singleton CentralMemory instance (for testing)."""
    global _center
    _center = None
