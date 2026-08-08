"""MemoryCompactMixin — memory pressure, compaction, and stats.

Extracted from memory.py (MemoryManager): pressure assessment (pressure),
low-importance merging (compact), stub compaction of old tool results
(stub_compact), and ring usage stats (stats). Composed by MemoryManager
alongside MemoryPersistMixin.
"""

from __future__ import annotations

import logging
from collections import deque

from l1.kernel.params.system import (
    LOG_TRUNC_100,
    LOG_TRUNC_120,
    LOG_TRUNC_150,
    LOG_TRUNC_500,
    MEMORY_PRESSURE_HIGH,
    MEMORY_PRESSURE_MEDIUM,
)

from .memory_quality import _suggest_compact
from .memory_ring import _estimate_tokens

logger = logging.getLogger(__name__)


class MemoryCompactMixin:
    """Memory pressure assessment, compaction, and usage stats."""

    PRESSURE_HIGH: float = MEMORY_PRESSURE_HIGH
    PRESSURE_MEDIUM: float = MEMORY_PRESSURE_MEDIUM

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
            summary_content = "; ".join(f"[{e.entry_type}] {e.content[:LOG_TRUNC_120]}" for e in group_entries)[
                :LOG_TRUNC_500
            ]
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

    def stub_compact(
        self,
        agent_id: str | None = None,
        keep_recent_turns: int = 1,
        min_collapse_size: int = LOG_TRUNC_500,
        exempt_tools: tuple[str, ...] = ("read_file",),
    ) -> dict:
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
            logger.info("stub_compact: %d entries stubbed, ~%d bytes saved", stubbed, saved_bytes)
        return {"stubbed": stubbed, "saved_bytes": saved_bytes}

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
            "level": level,
            "working_pct": round(w_pct, 2),
            "short_pct": round(s_pct, 2),
            "long_pct": round(l_pct, 2),
        }

    def stats(self) -> dict:
        """Return memory usage stats across all three rings."""
        return {
            "working": {
                "entries": self.working.count(),
                "tokens": self.working.token_count(),
                "budget": self.working.max_tokens,
            },
            "short": {
                "entries": self.short.count(),
                "tokens": self.short.token_count(),
                "budget": self.short.max_tokens,
            },
            "long": {"entries": self.long.count(), "tokens": self.long.token_count(), "budget": self.long.max_tokens},
        }
