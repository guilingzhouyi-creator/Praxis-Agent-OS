"""L3ASummaryStore — L3A's dedicated deliberation-memory space (旁路).

Independent of the shared R1-R3 MemoryManager rings (which serve Cell agents):
  - Cache: in-memory dict (bounded by L3A_SUMMARY_CACHE_MAX)
  - Persist: JSONL under data_dir/l3a_summaries/ (append-only, restorable)
  - Cold backup: one R3 entry per summary (tag-isolated, agent=l3a)

Each summary is the L3A-level distilled conclusion of one convention:
  issue_id, source_card_id, title, domain, agents, decisions, issues,
  overlap_notes (second-pass dedup on top of in-Cell dedup), summary text,
  doc_path + archive_ref for on-demand re-query of the source .md.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from . import params as _p

from l3.error_bus import capture

logger = logging.getLogger(__name__)

_L3A_SUMMARY_DIR = "l3a_summaries"
_L3A_SUMMARY_CACHE_MAX = 200
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "be", "this", "that", "should", "we", "our",
    "how", "what", "why", "when", "it", "as", "by", "at", "from", "do", "not",
})


@dataclass
class L3ASummary:
    issue_id: str = ""
    source_card_id: str = ""
    title: str = ""
    domain: str = ""
    created_at: float = field(default_factory=time.time)
    session_id: str = ""
    last_modified_at: float = field(default_factory=time.time)
    last_accessed_at: float = 0.0
    agents: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    overlap_notes: list[str] = field(default_factory=list)
    summary: str = ""
    doc_path: str = ""
    archive_ref: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class L3ASummaryStore:
    def __init__(self, persist_dir: str = ""):
        try:
            from l1.kernel.paths import get_paths as _gp
            base = _gp().data_dir
        except Exception:
            base = ".praxis"
        self._dir = persist_dir or os.path.join(base, _L3A_SUMMARY_DIR)
        self._lock = threading.RLock()
        self._cache: OrderedDict[str, L3ASummary] = OrderedDict()
        self._restore()

    # ── Persistence ──

    def _restore(self) -> None:
        if not os.path.isdir(self._dir):
            return
        try:
            for fn in sorted(os.listdir(self._dir)):
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(self._dir, fn)
                try:
                    with open(path, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            data = json.loads(line)
                            s = L3ASummary(**{k: v for k, v in data.items()
                                              if k in L3ASummary.__dataclass_fields__})
                            self._cache[s.issue_id] = s
                            if len(self._cache) > _L3A_SUMMARY_CACHE_MAX:
                                self._cache.popitem(last=False)
                except Exception:
                    capture("l3a summaries: restore failed", error_code="E_L3A_SUMMARY", component="l3a", context={"path": path})
                    logger.warning("l3a summaries: restore failed for %s", path)
        except Exception as e:
            capture("l3a summaries: restore dir failed", error_code="E_L3A_SUMMARY", component="l3a", context={"error": str(e)})
            logger.warning("l3a summaries: restore dir failed: %s", e)

    def _append(self, s: L3ASummary) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            path = os.path.join(self._dir, f"{s.issue_id}.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(s.to_dict(), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            capture("l3a summaries: persist failed", error_code="E_L3A_SUMMARY", component="l3a", context={"error": str(e)})
            logger.warning("l3a summaries: persist failed: %s", e)

    # ── Write (system-managed timestamps) ──

    def save(self, summary: L3ASummary) -> None:
        """Save (or update) a summary.

        created_at preserved from first save; last_modified_at updated on
        every write; last_accessed_at updated by get()/search()/latest().
        """
        with self._lock:
            existing = self._cache.get(summary.issue_id)
            if existing:
                summary.created_at = existing.created_at
            summary.last_modified_at = time.time()
            self._cache[summary.issue_id] = summary
            if len(self._cache) > _L3A_SUMMARY_CACHE_MAX:
                self._cache.popitem(last=False)
        self._append(summary)
        # Cold backup into L3A's own R3 ring (isolated instance)
        try:
            from l3.memory.central_memory import get_l3a_memory
            get_l3a_memory().remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_summary",
                content=json.dumps(summary.to_dict(), ensure_ascii=False, default=str),
                tags=["l3a", "summary", summary.domain, summary.issue_id],
                importance=0.8,
                ring=3,
            )
        except Exception:
            capture("l3a summaries: R3 cold backup failed", error_code="E_L3A_SUMMARY", component="l3a")
            logger.debug("l3a summaries: R3 cold backup failed")
        logger.info("l3a summary saved: %s — %s (session=%s)",
                    summary.issue_id, summary.title[:60], summary.session_id)

    # ── Read (system-managed last_accessed_at) ──

    def _touch(self, s: L3ASummary) -> None:
        s.last_accessed_at = time.time()
        try:
            self._append(s)
        except Exception:
            pass

    def get(self, issue_id: str) -> L3ASummary | None:
        with self._lock:
            s = self._cache.get(issue_id)
        if s:
            self._touch(s)
        return s

    def latest(self, domain: str = "", limit: int = 5) -> list[L3ASummary]:
        with self._lock:
            items = list(self._cache.values())
        items.sort(key=lambda s: s.created_at, reverse=True)
        if domain:
            items = [s for s in items if s.domain == domain]
        picked = items[:limit]
        for s in picked:
            self._touch(s)
        return picked

    def search(self, query: str, limit: int = 5) -> list[L3ASummary]:
        q = query.lower()
        with self._lock:
            items = list(self._cache.values())
        hits = []
        for s in items:
            haystack = " ".join([
                s.title, s.domain, s.summary,
                " ".join(d.get("text", "") for d in s.decisions),
            ]).lower()
            if q in haystack or any(q in w.lower() for w in s.title.split()):
                hits.append(s)
        hits.sort(key=lambda s: s.created_at, reverse=True)
        picked = hits[:limit]
        for s in picked:
            self._touch(s)
        return picked

    def count(self) -> int:
        with self._lock:
            return len(self._cache)

    def all(self) -> list[dict]:
        with self._lock:
            return [s.to_dict() for s in self._cache.values()]


# ── Second-pass dedup analysis (on top of in-Cell dedup) ──

def _keywords(text: str) -> set[str]:
    words = set()
    for w in text.lower().split():
        w = "".join(c for c in w if c.isalnum())
        if w and len(w) > 2 and w not in _STOPWORDS:
            words.add(w)
    return words


def analyze_overlap(issues: list[dict]) -> list[str]:
    """Detect answer overlap between issue blocks (second-pass dedup).

    issues: list of {"anchor", "title", "answer", "assigned_to"}.
    Returns human-readable overlap notes for the L3A summary.
    """
    notes = []
    answers = [(i.get("anchor", "?"), i.get("assigned_to", "?"),
                i.get("answer", "")) for i in issues if i.get("answer")]
    for i in range(len(answers)):
        for j in range(i + 1, len(answers)):
            a1, a2 = answers[i], answers[j]
            k1, k2 = _keywords(a1[2]), _keywords(a2[2])
            if not k1 or not k2:
                continue
            inter = k1 & k2
            union = k1 | k2
            jaccard = len(inter) / len(union) if union else 0.0
            if jaccard >= 0.4:
                notes.append(
                    f"[{a1[0]}] {a1[1]} overlaps [{a2[0]}] {a2[1]} "
                    f"({len(inter)} shared terms: {', '.join(sorted(inter)[:5])})"
                )
    return notes


def build_summary(issue_id: str, source_card_id: str, title: str,
                  domain: str, agents: list[str],
                  issues: list[dict], decisions: list[dict],
                  doc_path: str = "", archive_ref: str = "",
                  session_id: str = "") -> L3ASummary:
    """Rule-based L3A summary distillation from a converged convention."""
    overlap = analyze_overlap(issues)
    resolved = [i for i in issues if i.get("status") == "resolved"]
    lines = []
    if decisions:
        lines.append("Decisions:")
        for d in decisions:
            lines.append(f"- {d.get('text', '')}")
    elif resolved:
        lines.append("Resolved issues:")
        for i in resolved:
            lines.append(f"- {i.get('title', '')} → {i.get('answer', '')[:120]}")
    if overlap:
        lines.append("")
        lines.append("Overlap (second-pass dedup):")
        for n in overlap:
            lines.append(f"- {n}")
    if not lines:
        lines.append("(no decisions recorded)")
    return L3ASummary(
        issue_id=issue_id, source_card_id=source_card_id,
        title=title, domain=domain, agents=agents,
        issues=issues, decisions=decisions, overlap_notes=overlap,
        summary="\n".join(lines), doc_path=doc_path, archive_ref=archive_ref,
        session_id=session_id,
    )


# ── Singleton ──

_store: L3ASummaryStore | None = None


def get_store() -> L3ASummaryStore:
    global _store
    if _store is None:
        _store = L3ASummaryStore()
    return _store


def reset_store() -> None:
    global _store
    _store = None
