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

import json
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str, provider: str = "") -> int:
    """Token count estimation with optional provider-specific accuracy.

    Accuracy hierarchy:
      1. tiktoken (if installed) — exact, matches OpenAI/DeepSeek
      2. Anthropic heuristic: ~3.5 chars/token for English, ~1 for CJK
      3. Fallback: len/4

    The memory RingLayer uses this for budget management — it doesn't need
    to be exact, just consistent across entries.  When real token counts
    are available from LLM API responses (input_tokens, output_tokens),
    they override this estimate at storage time.
    """
    try:
        import tiktoken as _tk
        enc = _tk.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception as e:
        logger.warning("services/memory: %s", e)

    if provider == "anthropic":
        # Anthropic: ~3.5 chars/token for English, ~1 for CJK
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
        eng = len(text) - cjk
        return max(1, eng // 4 + cjk)

    return max(1, len(text) // 4)


from .memory_ring import MemEntry, RingLayer, _estimate_tokens
from .memory_quality import _score_importance, _is_good_memory, _suggest_compact, _MIN_CONTENT_LEN


class MemoryManager:
    """Agent memory manager — context window + ring tiers."""

    def __init__(self, working_budget: int = 8192, short_budget: int = 32768, long_budget: int = 131072):
        from l1.kernel.params.system import (
            MEMORY_RECALL_LIMIT,
            MEMORY_RECALL_LIMIT_LARGE,
            MEMORY_BUILD_CONTEXT_ENTRIES,
            MEMORY_PAGER_RECALL_LIMIT,
            MEMORY_RING_WORKING_TTL,
            MEMORY_RING_SHORT_TTL,
            MEMORY_RING_LONG_TTL,
        )
        self.working = RingLayer("working", working_budget, ttl=MEMORY_RING_WORKING_TTL)
        self.short = RingLayer("short", short_budget, ttl=MEMORY_RING_SHORT_TTL)
        self.long = RingLayer("long", long_budget, ttl=MEMORY_RING_LONG_TTL if MEMORY_RING_LONG_TTL else None)
        self._persist_dir: Path | None = None

    def set_persist_dir(self, path: str) -> None:
        """Set the persistence directory for Ring 2 (JSONL) and Ring 3 (SQLite).
        
        Called by boot.py during startup and shutdown_to_memories().
        """
        self._persist_dir = Path(path)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    def remember(self, agent_id: str, entry_type: str, content: str,
                 tags: list[str] | None = None, source: str = "",
                 importance: float = 0.5, ring: int = 1,
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
            logger.debug("memory REJECTED [%s] %s: %s", entry_type, reason, content[:60])
            return f"REJECTED:{reason}"

        if importance == 0.5:
            importance = _score_importance(content, entry_type)

        eid = f"mem-{int(time.time()*1000)}-{id(content)%10000:04x}"
        tok = real_tokens if real_tokens is not None else 0

        # Attach provenance if available
        if provenance is None:
            try:
                from .content_trust import get_trust as _gt
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
        logger.debug("memory stored [%s] ring=%d imp=%.2f tokens=%d: %s",
                     entry_type, ring, importance, entry.tokens, content[:80])
        return eid

    def recall(self, agent_id: str | None = None, entry_type: str | None = None,
               tag: str | None = None, rings: list[int] | None = None,
               limit: int = 20, cell_id: str | None = None) -> list[MemEntry]:
        """Query across rings."""
        rings = rings or [1, 2, 3]
        results: list[MemEntry] = []
        for r in rings:
            results.extend(self._ring(r).query(agent_id, entry_type, tag, limit))
        if cell_id:
            results = [e for e in results if e.cell_id == cell_id]
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]

    def build_context(self, agent_id: str, max_tokens: int = 4096) -> str:
        """Build an LLM context string from all rings, token-budgeted.

        Context watermarks are injected for traceability:
          - Watermark ID (unique per call)
          - Timestamp, token budget, agent ID
        """
        parts = []
        remaining = max_tokens

        # Context watermark — helps debug which context version was used
        _ctx_id = f"ctx-{int(time.time() * 1000):x}"
        _watermark = (
            f"<!-- WATERMARK: id={_ctx_id} agent={agent_id} "
            f"budget={max_tokens} -->"
        )
        parts.append(_watermark)
        remaining -= len(_watermark)

        # Working memory first (most recent, highest priority)
        w = self.working.summarize(agent_id)
        if w:
            tok = _estimate_tokens(w)
            if tok <= remaining:
                parts.append("=== Working Memory ===\n" + w)
                remaining -= tok

        # Then short-term
        s = self.short.summarize(agent_id)
        if s:
            tok = _estimate_tokens(s)
            if tok <= remaining:
                parts.append("=== Recent History ===\n" + s)
                remaining -= tok

        # Finally long-term (tag-matched)
        from l1.kernel.params.system import MEMORY_BUILD_CONTEXT_LIMIT
        l_entries = self.long.query(agent_id=agent_id, limit=MEMORY_BUILD_CONTEXT_LIMIT)
        if l_entries:
            l_text = "\n".join(f"[{e.entry_type}] {e.content[:300]}" for e in l_entries)
            tok = _estimate_tokens(l_text)
            if tok <= remaining:
                parts.append("=== Knowledge ===\n" + l_text)

        return "\n\n".join(parts)

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
        and replaces them with a single summary entry in Ring 2.
        """
        from l1.kernel.params.agent import SCOUT_RECALL_LIMIT
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
            summary_content = "; ".join(
                f"[{e.entry_type}] {e.content[:120]}"
                for e in group_entries
            )[:500]
            self.remember(
                agent_id=group_entries[0].agent_id,
                entry_type="summary",
                content=summary_content,
                tags=list(set(t for e in group_entries for t in e.tags)),
                ring=2,
                importance=0.6,
            )
            for e in group_entries:
                for layer in (self.working, self.short):
                    layer._entries = deque(
                        [x for x in layer._entries if x.id != e.id],
                        maxlen=layer.max_entries,
                    )
                    layer._rebuild_token_count()
        return {"merged": merged, "saved_tokens": saved_tokens, "candidates": len(candidates)}

    def stub_compact(self, agent_id: str | None = None,
                      keep_recent_turns: int = 1,
                      min_collapse_size: int = 500,
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
            if e.entry_type == "tool_call" and any(t in e.content[:100] for t in exempt_tools):
                continue
            # Skip recent turns
            if str(int(e.timestamp)) in recent_ts:
                continue
            # Stub: replace content with summary
            head = e.content[:150]
            e.content = f"[stubbed] {head}... ({len(e.content)} chars elided)"
            e.tokens = _estimate_tokens(e.content)
            saved_bytes += len(e.content)
            stubbed += 1

        if stubbed > 0:
            logger.info("stub_compact: %d entries stubbed, ~%d bytes saved",
                        stubbed, saved_bytes)
        return {"stubbed": stubbed, "saved_bytes": saved_bytes}

    PRESSURE_HIGH: float = 0.80   # ≥80% token usage = high pressure
    PRESSURE_MEDIUM: float = 0.60

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
        return {
            "working": {"entries": self.working.count(), "tokens": self.working.token_count(), "budget": self.working.max_tokens},
            "short": {"entries": self.short.count(), "tokens": self.short.token_count(), "budget": self.short.max_tokens},
            "long": {"entries": self.long.count(), "tokens": self.long.token_count(), "budget": self.long.max_tokens},
        }

    # ── Persistence: dual storage ──
    #   Ring 2 → JSONL (append-only session log)
    #   Ring 3 → SQLite FTS5 (full-text searchable knowledge)
    #   Ring 1 → in-memory only (ephemeral)

    def _jsonl_path(self) -> Path:
        from l1.kernel.params.system import MEMORY_PERSIST_FILE_RING2, PRAXIS_DATA_DIR
        return (self._persist_dir or Path(PRAXIS_DATA_DIR)) / MEMORY_PERSIST_FILE_RING2

    def _db_path(self) -> Path:
        from l1.kernel.params.system import MEMORY_PERSIST_FILE_RING3, PRAXIS_DATA_DIR
        return (self._persist_dir or Path(PRAXIS_DATA_DIR)) / MEMORY_PERSIST_FILE_RING3

    def _ensure_ring3_db(self) -> None:
        """Create Ring 3 SQLite table with FTS5 if not exists."""
        import sqlite3
        db = self._db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db), check_same_thread=False)
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
        """Persist Ring 2 → JSONL, Ring 3 → SQLite FTS5."""
        p = Path(path) if path else self._persist_dir
        if not p:
            return {"success": False, "error": "no path configured"}
        p.mkdir(parents=True, exist_ok=True)
        self._persist_dir = p

        # Ring 2 → JSONL (append-only)
        jsonl_path = self._jsonl_path()
        short_entries = self.short.to_dict()
        if short_entries:
            with open(jsonl_path, "a", encoding="utf-8") as f:
                for e in short_entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

        # Ring 3 → SQLite FTS5
        self._ensure_ring3_db()
        import sqlite3
        conn = sqlite3.connect(str(self._db_path()), check_same_thread=False)
        long_entries = self.long.to_dict()
        for e in long_entries:
            conn.execute(
                "INSERT OR REPLACE INTO knowledge (id, agent, type, content, tags, importance, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (e["id"], e["agent_id"], e["entry_type"], e["content"],
                 ",".join(e.get("tags", [])), e.get("importance", 0.5), e.get("timestamp", time.time())),
            )
        conn.commit()
        conn.close()
        return {"success": True, "short_written": len(short_entries), "long_written": len(long_entries)}

    def restore(self, path: str | None = None,
                ring2_limit: int = 0, ring3_limit: int = 0) -> dict:
        """Restore Ring 2 from JSONL, Ring 3 from SQLite FTS5.

        Args:
            path: Persist directory. Defaults to configured path.
            ring2_limit: Max JSONL lines to restore (0 = unlimited).
            ring3_limit: Max SQLite rows to restore (0 = unlimited).
        """
        p = Path(path) if path else self._persist_dir
        if not p:
            return {"success": False, "error": "no path configured"}
        self._persist_dir = p
        total = 0

        # Ring 2 ← JSONL
        jsonl_path = self._jsonl_path()
        if jsonl_path.exists():
            with open(jsonl_path, "r", encoding="utf-8") as f:
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
        db_path = self._db_path()
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

    def search_long_term(self, query: str, agent_id: str | None = None, limit: int = 10) -> list[dict]:
        """FTS5 full-text search across Ring 3 knowledge base."""
        db_path = self._db_path()
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
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            return [
                {"id": r[0], "agent_id": r[1], "entry_type": r[2], "content": r[3][:500],
                 "tags": r[4].split(","), "importance": r[5], "timestamp": r[6]}
                for r in rows
            ]
        except Exception:
            return []

    def forget_agent(self, agent_id: str) -> dict:
        return {
            "working": self.working.clear_agent(agent_id),
            "short": self.short.clear_agent(agent_id),
            "long": self.long.clear_agent(agent_id),
        }

    def forget_cell(self, cell_id: str) -> dict:
        return {
            "working": self.working.forget_cell(cell_id),
            "short": self.short.forget_cell(cell_id),
            "long": self.long.forget_cell(cell_id),
        }

    def _ring(self, n: int) -> RingLayer:
        return {1: self.working, 2: self.short, 3: self.long}.get(n, self.working)

    def _ttl_for(self, ring: int) -> float:
        return {1: 1800, 2: 86400, 3: 0}.get(ring, 0)


_memory: MemoryManager | None = None


def get_memory() -> MemoryManager:
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory


def reset_memory() -> None:
    global _memory
    _memory = None
