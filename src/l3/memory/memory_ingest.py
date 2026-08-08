"""MemoryIngestMixin — memory write path: remember, promote, entry lookup.

Extracted from memory.py (MemoryManager): quality-validated storage
(remember), ring promotion (promote), graph-edge recent snapshot
(_recent_entries), and single-entry lookup (get_entry). Composed by
MemoryManager alongside MemoryPersistMixin.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque

from l1.kernel.params.system import HASH_TRUNC_LONG, LOG_TRUNC_60, LOG_TRUNC_80, MEMORY_IMPORTANCE_BASE

from .memory_quality import _is_good_memory, _score_importance
from .memory_ring import MemEntry

logger = logging.getLogger(__name__)


class MemoryIngestMixin:
    """Memory write path: quality-validated remember and ring promotion."""

    def remember(
        self,
        agent_id: str,
        entry_type: str,
        content: str,
        tags: list[str] | None = None,
        source: str = "",
        importance: float = MEMORY_IMPORTANCE_BASE,
        ring: int = 1,
        real_tokens: int | None = None,
        provenance: dict | None = None,
        cell_id: str = "",
    ) -> str:
        """Store a memory entry with quality validation.

        Args:
            real_tokens: If provided (from LLM API response), overrides
                         the internal _estimate_tokens for accurate budgeting.

        Returns entry ID on success, or error string prefixed with 'REJECTED:'.
        """
        accepted, reason = _is_good_memory(content, entry_type)
        if not accepted:
            logger.debug("memory REJECTED [%s] %s: %s", entry_type, reason, content[:LOG_TRUNC_60])
            return f"REJECTED:{reason}"

        if importance == MEMORY_IMPORTANCE_BASE:
            importance = _score_importance(content, entry_type)

        eid = f"mem-{uuid.uuid4().hex[:HASH_TRUNC_LONG]}"
        tok = real_tokens if real_tokens is not None else 0

        # Attach provenance if available
        if provenance is None:
            try:
                from .services.content_trust import get_trust as _gt

                ct = _gt()
                st = "agent" if agent_id else "tool"
                prov = ct.tag(st, source_id=agent_id or source, method=entry_type, trace_id="")
                provenance = prov.to_dict()
            except Exception:
                provenance = {}
        entry = MemEntry(
            id=eid,
            agent_id=agent_id,
            cell_id=cell_id,
            entry_type=entry_type,
            content=content,
            tokens=tok,
            tags=tags or [],
            source=source,
            importance=importance,
            ttl=self._ttl_for(ring),
        )
        entry.provenance = provenance
        layer = self._ring(ring)
        layer.push(entry)
        # Mark as dirty for incremental persist (thread-safe)
        with self._lock:
            if ring == 2:
                self._dirty_short.add(eid)
            elif ring == 3:
                self._dirty_long.add(eid)
        # ── R5 swarm-domain graph hook (off by default; failures do not affect the main flow) ──
        try:
            from .memory_graph import get_graph as _get_graph

            _recent = self._recent_entries(agent_id, cell_id, limit=3)
            _get_graph().remember_hook(
                entry_id=eid,
                agent_id=agent_id,
                entry_type=entry_type,
                cell_id=cell_id,
                recent=_recent,
                created_by=agent_id or "system",
            )
        except Exception:
            logger.debug("memory_graph: hook failed")  # graph is derived layer
        logger.debug(
            "memory stored [%s] ring=%d imp=%.2f tokens=%d: %s",
            entry_type,
            ring,
            importance,
            entry.tokens,
            content[:LOG_TRUNC_80],
        )
        return eid

    def _recent_entries(self, agent_id: str, cell_id: str, limit: int = 3) -> list[dict]:
        """Snapshot the most recent entries (for graph edge building).

        Collected before pushing the new entry — provides the "previous"
        context the graph needs for sequential/type/cell chains.
        """
        recent: list[dict] = []
        try:
            for layer in (self.long, self.short, self.working):
                with layer._lock:
                    for e in reversed(list(layer._entries)):
                        if len(recent) >= limit:
                            break
                        recent.append(
                            {
                                "id": e.id,
                                "entry_type": e.entry_type,
                                "agent_id": e.agent_id,
                                "cell_id": e.cell_id,
                            }
                        )
                if len(recent) >= limit:
                    break
        except Exception:
            logger.debug("memory: recent memory query failed, returning partial", exc_info=True)
        return recent

    def promote(self, entry_id: str, target_ring: int) -> dict:
        """Move an entry between memory rings.

        Finds the entry across all rings, copies it to *target_ring*,
        and removes it from its source ring.

        Returns:
            {"success": True, "entry_id": str, "from_ring": int, "to_ring": int}
            or {"success": False, "error": str}
        """
        source_entry: MemEntry | None = None
        source_ring: int = 0
        for ring_num, layer in ((1, self.working), (2, self.short), (3, self.long)):
            with layer._lock:
                for e in layer._entries:
                    if e.id == entry_id:
                        source_entry = e
                        source_ring = ring_num
                        break
            if source_entry:
                break
        if not source_entry:
            return {"success": False, "error": f"entry not found: {entry_id}"}

        # Remember in target ring (goes through dirty tracking)
        new_id = self.remember(
            agent_id=source_entry.agent_id,
            entry_type=source_entry.entry_type,
            content=source_entry.content,
            tags=source_entry.tags,
            source=source_entry.source,
            importance=source_entry.importance,
            cell_id=source_entry.cell_id,
            ring=target_ring,
        )

        # Remove from source ring
        for layer in (self.working, self.short, self.long):
            with layer._lock:
                old_entries = list(layer._entries)
                removed = [e for e in old_entries if e.id == entry_id]
                if removed:
                    layer._entries = deque(
                        [e for e in layer._entries if e.id != entry_id],
                        maxlen=layer.max_entries,
                    )
                    layer._rebuild_token_count()
                    break

        return {"success": True, "entry_id": new_id, "from_ring": source_ring, "to_ring": target_ring}

    def get_entry(self, entry_id: str) -> MemEntry | None:
        """Look up a single entry by id across all rings (early-exit scan).

        Preferred over ``recall(limit=N)`` + ``next(...)`` when only one entry
        is needed — this avoids building/sorting the full result list.
        """
        if not entry_id:
            return None
        for ring_num in (1, 2, 3):
            layer = self._ring(ring_num)
            with layer._lock:
                for e in layer._entries:
                    if e.id == entry_id:
                        return e
        return None
