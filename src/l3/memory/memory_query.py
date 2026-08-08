"""MemoryQueryMixin — memory read path: recall, context, quality, search.

Extracted from memory.py (MemoryManager): cross-ring query (recall), LLM
context assembly (build_context), quality distribution report
(quality_report), FTS5 search (search_long_term), and the ring snapshots
(working_entries / short_term). Composed by MemoryManager alongside
MemoryPersistMixin.
"""

from __future__ import annotations

import logging

from l1.kernel.params.system import (
    CONTEXT_BUILD_MAX_TOKENS,
    LOG_TRUNC_200,
    MEMORY_PROMOTION_THRESHOLD,
    MEMORY_RECALL_LIMIT_LARGE,
)

from .memory_context import build_context as _build_context
from .memory_quality import _suggest_compact
from .memory_ring import MemEntry
from .memory_search import search_long_term as _search_long_term

logger = logging.getLogger(__name__)


class MemoryQueryMixin:
    """Memory read path: recall, context assembly, quality, and search."""

    def recall(
        self,
        agent_id: str | None = None,
        entry_type: str | None = None,
        tag: str | None = None,
        rings: list[int] | None = None,
        limit: int = 20,
        cell_id: str | None = None,
        promote_to_cell: str = "",
        graph_diffusion: bool = False,
    ) -> list[MemEntry]:
        """Query across rings.

        Args:
            promote_to_cell: If set, promotes important entries (importance ≥ 0.6)
                             back to the given Cell's L2 cache so other agents
                             in the same Cell can find them via cell.cache.search().
            graph_diffusion: If set (and R5 graph enabled), expands results
                             along graph edges from the linear hits (subgraph navigation).
        """
        rings = rings or [1, 2, 3]
        results: list[MemEntry] = []
        for r in rings:
            results.extend(self._ring(r).query(agent_id, entry_type, tag, limit))
        if cell_id:
            results = [e for e in results if e.cell_id == cell_id]
        results.sort(key=lambda e: e.timestamp, reverse=True)
        results = results[:limit]

        # ── R5 swarm-domain graph diffusion (toggle-controlled; falls back to linear on failure) ──
        if graph_diffusion:
            try:
                from .memory_graph import get_graph as _get_graph

                g = _get_graph()
                if g.enabled:
                    seeds = [e.id for e in results[:5]]
                    gr = g.recall(seeds, depth=2, limit=limit)
                    if gr["nodes"]:
                        by_id = {e.id: e for e in results}
                        nodes: list[MemEntry] = []
                        for nid in gr["nodes"]:
                            e = by_id.get(nid)
                            if e and e not in nodes:
                                nodes.append(e)
                        for e in results:
                            if e not in nodes and len(nodes) < limit:
                                nodes.append(e)
                        results = nodes[:limit]
            except Exception:
                logger.debug("memory: graph diffusion failed")

        # Auto-promote important results to Cell L2 cache
        if promote_to_cell and results:
            try:
                from l3.cell import get_cell as _get_cell

                cell = _get_cell(promote_to_cell)
                for e in results:
                    if e.importance >= MEMORY_PROMOTION_THRESHOLD and e.content:
                        cell.cache.promote(
                            key=f"mem:{e.agent_id}:{e.entry_type}:{e.id[-12:]}",
                            summary=e.content[:LOG_TRUNC_200],
                            value=e.content,
                            location="l3",
                            importance=e.importance,
                        )
            except Exception:
                logger.debug("memory: promote failed")  # best-effort

        return results

    def build_context(self, agent_id: str, max_tokens: int = CONTEXT_BUILD_MAX_TOKENS) -> str:
        """Build an LLM context string from all rings, token-budgeted.

        Context watermarks are injected for traceability.
        Delegates to memory_context.py.
        """
        return _build_context(self, agent_id, max_tokens=max_tokens)

    def quality_report(self, agent_id: str | None = None) -> dict:
        """Report memory quality distribution for an agent."""
        entries = self.recall(agent_id=agent_id, limit=MEMORY_RECALL_LIMIT_LARGE)
        by_quality = {"good": 0, "ok": 0, "weak": 0}
        by_type: dict[str, int] = {}
        for e in entries:
            q = e.quality_note()
            by_quality[q] = by_quality.get(q, 0) + 1
            by_type[e.entry_type] = by_type.get(e.entry_type, 0) + 1
        suggestions = _suggest_compact(entries)
        return {
            "total": len(entries),
            "quality": by_quality,
            "by_type": by_type,
            "compact_candidates": suggestions[:5],
            "token_usage": self.stats(),
        }

    def search_long_term(self, query: str, agent_id: str | None = None, limit: int = 10) -> list[dict]:
        """FTS5 full-text search across Ring 3 knowledge base. Delegates to memory_search.py."""
        return _search_long_term(self, query, agent_id=agent_id, limit=limit)

    def working_entries(self) -> list[MemEntry]:
        """Return a snapshot of all Ring 1 (working) entries.

        Used by Swapper for pressure-based swap-out decisions.
        """
        with self.working._lock:
            return list(self.working._entries)

    def short_term(self) -> list[MemEntry]:
        """Return a snapshot of all Ring 2 (short-term) entries.

        Used by Swapper for compaction decisions.
        """
        with self.short._lock:
            return list(self.short._entries)
