"""Agent memory management — context window, ring tiers, retrieval.

Architecture:
  Working:   Current task context (Ring 1, token-budgeted for LLM window)
  ShortTerm: Session history (Ring 2, auto-compressed via swapper)
  LongTerm:  Project knowledge (Ring 3, persistent, archived)

Memory quality rules (aligning with Hermes Agent standards):
  GOOD:  high density, actionable, specific to env/user/project
  BAD:   too vague, too verbose, trivially re-searchable, raw data
  REJECT: raw logs/code >500 chars, temp debug paths, obvious facts

  What to save:
    - Environment facts: OS, tools, versions, ports, paths
    - Project conventions: framework, test style, CI, deploy
    - Lessons learned: "port 2222 not 22", "run make test not pytest"
    - User preferences: concise replies, specific dislikes
    - Completed work: what was done and when

  What NOT to save:
    - Obvious: "Python lists are mutable" (searchable)
    - Raw data: log dumps, large code blocks, SQL results
    - Temporary: debug file paths, one-off build artifacts
    - Duplicate: already in constitution / config / context
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from pathlib import Path

from l1.kernel.params.system import (
    CONTEXT_BUILD_MAX_TOKENS,
    HASH_TRUNC_LONG,
    LOG_TRUNC_60,
    LOG_TRUNC_80,
    LOG_TRUNC_100,
    LOG_TRUNC_120,
    LOG_TRUNC_150,
    LOG_TRUNC_200,
    LOG_TRUNC_500,
    MEMORY_IMPORTANCE_BASE,
    MEMORY_PRESSURE_HIGH,
    MEMORY_PRESSURE_MEDIUM,
    MEMORY_PROMOTION_THRESHOLD,
    MEMORY_RECALL_LIMIT_LARGE,
    MEMORY_RING_LONG_BUDGET,
    MEMORY_RING_LONG_TTL,
    MEMORY_RING_SHORT_BUDGET,
    MEMORY_RING_SHORT_TTL,
    MEMORY_RING_WORKING_BUDGET,
    MEMORY_RING_WORKING_TTL,
)

from .memory_context import build_context as _build_context
from .memory_quality import _is_good_memory, _score_importance, _suggest_compact
from .memory_ring import MemEntry, RingLayer, _estimate_tokens
from .memory_search import search_long_term as _search_long_term
from .memory_persist import MemoryPersistMixin

logger = logging.getLogger(__name__)


class MemoryManager(MemoryPersistMixin):
    """Agent memory manager — context window + ring tiers."""

    def __init__(self, working_budget: int = MEMORY_RING_WORKING_BUDGET, short_budget: int = MEMORY_RING_SHORT_BUDGET, long_budget: int = MEMORY_RING_LONG_BUDGET):
        self.working = RingLayer("working", working_budget, ttl=MEMORY_RING_WORKING_TTL)
        self.short = RingLayer("short", short_budget, ttl=MEMORY_RING_SHORT_TTL)
        self.long = RingLayer("long", long_budget, ttl=MEMORY_RING_LONG_TTL)
        self._persist_dir: Path | None = None
        # Dirty-entry tracking: set of entry IDs changed since last persist
        self._dirty_short: set[str] = set()
        self._dirty_long: set[str] = set()
        self._lock = threading.Lock()

    def set_persist_dir(self, path: str) -> None:
        """Set the persistence directory for Ring 2 (JSONL) and Ring 3 (SQLite).

        Called by boot.py during startup and shutdown_to_memories().
        """
        self._persist_dir = Path(path)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    def remember(self, agent_id: str, entry_type: str, content: str,
                 tags: list[str] | None = None, source: str = "",
                 importance: float = MEMORY_IMPORTANCE_BASE, ring: int = 1,
                 real_tokens: int | None = None,
                 provenance: dict | None = None,
                 cell_id: str = "") -> str:
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
                prov = ct.tag(st, source_id=agent_id or source,
                              method=entry_type, trace_id="")
                provenance = prov.to_dict()
            except Exception:
                provenance = {}
        entry = MemEntry(id=eid, agent_id=agent_id, cell_id=cell_id, entry_type=entry_type,
                         content=content, tokens=tok,
                         tags=tags or [], source=source,
                         importance=importance, ttl=self._ttl_for(ring))
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
                entry_id=eid, agent_id=agent_id, entry_type=entry_type,
                cell_id=cell_id, recent=_recent, created_by=agent_id or "system")
        except Exception:
            logger.debug("memory_graph: hook failed")  # graph is derived layer
        logger.debug("memory stored [%s] ring=%d imp=%.2f tokens=%d: %s",
                     entry_type, ring, importance, entry.tokens, content[:LOG_TRUNC_80])
        return eid

    def _recent_entries(self, agent_id: str, cell_id: str,
                        limit: int = 3) -> list[dict]:
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
                        recent.append({
                            "id": e.id, "entry_type": e.entry_type,
                            "agent_id": e.agent_id, "cell_id": e.cell_id,
                        })
                if len(recent) >= limit:
                    break
        except Exception:
            logger.debug("memory: recent memory query failed, returning partial", exc_info=True)
        return recent

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

        return {"success": True, "entry_id": new_id,
                "from_ring": source_ring, "to_ring": target_ring}

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

    def recall(self, agent_id: str | None = None, entry_type: str | None = None,
               tag: str | None = None, rings: list[int] | None = None,
               limit: int = 20, cell_id: str | None = None,
               promote_to_cell: str = "",
               graph_diffusion: bool = False) -> list[MemEntry]:
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

    def compact(self, agent_id: str | None = None, dry_run: bool = False) -> dict:
        """Merge low-importance entries into summaries.

        Finds groups of 3+ related entries (same agent + overlapping tags)
        and replaces them with a single summary entry.
        Target ring is chosen by group average importance:
          ≥ ARCHIVE_IMPORTANCE_THRESHOLD (0.7) → Ring 3 (Long-term)
          ≥ 0.4 → Ring 2 (Short-term)
          < 0.4 → Ring 1 (Working)
        """
        from l1.kernel.params.agent import ARCHIVE_IMPORTANCE_THRESHOLD, COMPACT_RING2_IMPORTANCE, SCOUT_RECALL_LIMIT
        entries = self.recall(agent_id=agent_id, rings=[1, 2], limit=SCOUT_RECALL_LIMIT)
        candidates = _suggest_compact(entries)
        merged = 0
        saved_tokens = 0
        for c in candidates[:5]:
            group_entries = [e for e in entries if e.id in c["entries"]]
            if not group_entries:
                continue
            merged += len(group_entries)
            saved_tokens += c["total_tokens"]
            if dry_run:
                continue
            avg_imp = sum(e.importance for e in group_entries) / len(group_entries)
            if avg_imp >= ARCHIVE_IMPORTANCE_THRESHOLD:
                target_ring = 3
            elif avg_imp >= COMPACT_RING2_IMPORTANCE:
                target_ring = 2
            else:
                target_ring = 1
            summary_content = "; ".join(
                f"[{e.entry_type}] {e.content[:LOG_TRUNC_120]}"
                for e in group_entries
            )[:LOG_TRUNC_500]
            self.remember(
                agent_id=group_entries[0].agent_id,
                entry_type="summary",
                content=summary_content,
                tags=list(set(t for e in group_entries for t in e.tags)),
                ring=target_ring,
                importance=avg_imp,
            )
            # Batch delete: collect all entry IDs, rebuild each layer once
            remove_ids = {e.id for e in group_entries}
            affected_layers = {self.working}
            if target_ring >= 2:
                affected_layers.add(self.short)
            if target_ring >= 3:
                affected_layers.add(self.long)
            for layer in affected_layers:
                layer._entries = deque(
                    [x for x in layer._entries if x.id not in remove_ids],
                    maxlen=layer.max_entries,
                )
                layer._rebuild_token_count()
        return {"merged": merged, "saved_tokens": saved_tokens, "candidates": len(candidates)}

    def stub_compact(self, agent_id: str | None = None,
                      keep_recent_turns: int = 1,
                      min_collapse_size: int = LOG_TRUNC_500,
                      exempt_tools: tuple[str, ...] = ("read_file",)) -> dict:
        """Stub-compact old tool results: replace full output with summary.

        AtomCode StubCompaction-style:
          - Entries ≤ min_collapse_size bytes are left alone
          - read_file results are never stubbed (model needs full context)
          - Most recent `keep_recent_turns` turns are kept full
          - Old tool results are replaced with a one-line summary
        """
        from l1.kernel.params.agent import SCOUT_RECALL_LIMIT
        entries = self.recall(agent_id=agent_id, rings=[1, 2, 3], limit=SCOUT_RECALL_LIMIT)
        # Find most recent turn timestamps to protect
        recent_ts: set[str] = set()
        if keep_recent_turns > 0:
            for e in sorted(entries, key=lambda x: x.timestamp, reverse=True):
                if e.entry_type == "tool_call":
                    recent_ts.add(str(int(e.timestamp)))
                if len(recent_ts) >= keep_recent_turns:
                    break

        stubbed = 0
        saved_bytes = 0
        for e in entries:
            # Skip already-stubbed entries
            if len(e.content) <= min_collapse_size:
                continue
            # Skip read-only tools
            if e.entry_type == "tool_call" and any(t in e.content[:LOG_TRUNC_100] for t in exempt_tools):
                continue
            # Skip recent turns
            if str(int(e.timestamp)) in recent_ts:
                continue
            # Stub: replace content with summary
            head = e.content[:LOG_TRUNC_150]
            e.content = f"[stubbed] {head}... ({len(e.content)} chars elided)"
            e.tokens = _estimate_tokens(e.content)
            saved_bytes += len(e.content)
            stubbed += 1

        if stubbed > 0:
            logger.info("stub_compact: %d entries stubbed, ~%d bytes saved",
                        stubbed, saved_bytes)
        return {"stubbed": stubbed, "saved_bytes": saved_bytes}

    PRESSURE_HIGH: float = MEMORY_PRESSURE_HIGH
    PRESSURE_MEDIUM: float = MEMORY_PRESSURE_MEDIUM

    def pressure(self, agent_id: str | None = None) -> dict:
        """Check memory pressure across all rings.

        Returns:
          {"level": "high"|"medium"|"low", "working_pct": float,
           "short_pct": float, "long_pct": float}
        """
        w_pct = self.working.token_count() / max(self.working.max_tokens, 1)
        s_pct = self.short.token_count() / max(self.short.max_tokens, 1)
        l_pct = self.long.token_count() / max(self.long.max_tokens, 1)
        max_pct = max(w_pct, s_pct, l_pct)
        if max_pct >= self.PRESSURE_HIGH:
            level = "high"
        elif max_pct >= self.PRESSURE_MEDIUM:
            level = "medium"
        else:
            level = "low"
        return {
            "level": level, "working_pct": round(w_pct, 2),
            "short_pct": round(s_pct, 2), "long_pct": round(l_pct, 2),
        }

    def stats(self) -> dict:
        """Return memory usage stats across all three rings."""
        return {
            "working": {"entries": self.working.count(), "tokens": self.working.token_count(), "budget": self.working.max_tokens},
            "short": {"entries": self.short.count(), "tokens": self.short.token_count(), "budget": self.short.max_tokens},
            "long": {"entries": self.long.count(), "tokens": self.long.token_count(), "budget": self.long.max_tokens},
        }

    # ── Persistence: dual storage ──
    #   Ring 2 → JSONL (append-only session log)
    #   Ring 3 → SQLite FTS5 (full-text searchable knowledge)
    #   Ring 1 → in-memory only (ephemeral)



    def search_long_term(self, query: str, agent_id: str | None = None, limit: int = 10) -> list[dict]:
        """FTS5 full-text search across Ring 3 knowledge base. Delegates to memory_search.py."""
        return _search_long_term(self, query, agent_id=agent_id, limit=limit)

    def forget_agent(self, agent_id: str, ring: int = 0) -> dict:
        """Remove all memory entries for a given agent from all rings."""
        if ring == 1:
            return {"working": self.working.clear_agent(agent_id)}
        if ring == 2:
            return {"short": self.short.clear_agent(agent_id)}
        if ring == 3:
            return {"long": self.long.clear_agent(agent_id)}
        return {
            "working": self.working.clear_agent(agent_id),
            "short": self.short.clear_agent(agent_id),
            "long": self.long.clear_agent(agent_id),
        }

    def forget_cell(self, cell_id: str) -> dict:
        """Remove all memory entries for a given cell from all rings."""
        return {
            "working": self.working.forget_cell(cell_id),
            "short": self.short.forget_cell(cell_id),
            "long": self.long.forget_cell(cell_id),
        }

    def _ring(self, n: int) -> RingLayer:
        return {1: self.working, 2: self.short, 3: self.long}.get(n, self.working)

    def _ttl_for(self, ring: int) -> float:
        return {1: MEMORY_RING_WORKING_TTL, 2: MEMORY_RING_SHORT_TTL, 3: MEMORY_RING_LONG_TTL}.get(ring, 0)


_memory: MemoryManager | None = None


def get_memory() -> MemoryManager:
    """Get the singleton MemoryManager instance."""
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory


def reset_memory() -> None:
    """Reset the singleton MemoryManager instance (for testing)."""
    global _memory
    _memory = None
