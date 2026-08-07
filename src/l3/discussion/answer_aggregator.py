"""AnswerAggregator — cross-Cell answer merge, dedup, coverage check, divergence detection.

Collects CellAnswer entries from all CellAnswerRepos (via Archive/Ring 3),
deduplicates by fingerprint, checks coverage completeness, identifies
divergence points, and extracts supplement issues.

Output: AggregatedReport with consistent view, divergence markers, and
supplement issues for re-routing.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from l1.kernel.params.system import HASH_TRUNC_LONG, LOG_TRUNC_80, LOG_TRUNC_100, LOG_TRUNC_200, LOG_TRUNC_500

logger = logging.getLogger(__name__)


@dataclass
class AggregatedReport:
    """Cross-Cell aggregated analysis of all answers."""

    session_id: str = ""
    status: str = ""  # "converged" | "partial" | "diverged"
    total_cells: int = 0
    participating_cells: list[str] = field(default_factory=list)
    answers_by_cell: dict[str, int] = field(default_factory=dict)
    dedup_map: dict[str, list[str]] = field(default_factory=dict)
    consistency: list[dict] = field(default_factory=list)
    divergences: list[dict] = field(default_factory=list)
    supplement_issues: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    merged_answer: dict = field(default_factory=dict)
    created_at: float = 0.0


class AnswerAggregator:
    """Collect, deduplicate, and analyze cross-Cell answers."""

    def collect(self, session_id: str) -> dict:
        """Full aggregation pipeline.

        1. Load all CellAnswer entries for session_id from Archive
        2. Fingerprint dedup
        3. Coverage check
        4. Divergence detection
        5. Supplement extraction
        6. Build merged answer
        """
        session_id = session_id
        answers = self._load_answers(session_id)
        if not answers:
            return {"success": False, "error": "no answers found"}

        # Group by cell
        by_cell: dict[str, list[dict]] = defaultdict(list)
        for a in answers:
            by_cell[a.get("cell_id", "?")].append(a)

        cells = list(by_cell.keys())

        # Dedup by fingerprint
        dedup_map = self._dedup(answers)

        # Coverage check
        coverage = self._check_coverage(answers)

        # Divergence detection
        divergences = self._find_divergences(answers)

        # Supplement extraction
        supplements = self._extract_supplements(answers)

        # Build merged answer
        merged = self._merge(answers)

        # Determine status
        if divergences and len(divergences) >= 2:
            status = "diverged"
        elif coverage.get("unanswered_issues"):
            status = "partial"
        else:
            status = "converged"

        return {
            "success": True,
            "session_id": session_id,
            "status": status,
            "total_cells": len(cells),
            "participating_cells": cells,
            "answers_by_cell": {c: len(by_cell[c]) for c in cells},
            "dedup_map": dedup_map,
            "consistency": self._find_consistency(answers, dedup_map),
            "divergences": divergences,
            "supplement_issues": supplements,
            "coverage": coverage,
            "merged_answer": merged,
        }

    # ── Loading ────────────────────────────────────────────────

    def _load_answers(self, session_id: str) -> list[dict]:
        """Load all CellAnswer entries for a session from the Archive."""
        results = []
        try:
            from l3.memory.memory import get_memory

            mem = get_memory()
            recalled = mem.recall(agent_id="", entry_type="discussion.*", tags=[session_id], limit=1000)
            for r in recalled:
                content = r.get("content", "")
                if content:
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            parsed["agent_id"] = r.get("agent_id", "")
                            parsed["cell_id"] = r.get("cell_id", "")
                            results.append(parsed)
                    except Exception:
                        results.append(
                            {
                                "content": content[:LOG_TRUNC_200],
                                "agent_id": r.get("agent_id", ""),
                                "cell_id": r.get("cell_id", ""),
                            }
                        )
        except Exception as e:
            logger.warning("aggregator: load answers: %s", e)

        if not results:
            # Fallback: try loading from Archive directly
            try:
                from l3.tools._archive import archive_search

                search = archive_search
                # Use fonds pattern
                fonds_pattern = f"%{session_id}%"
                rows = search({"fonds": fonds_pattern})
                if isinstance(rows, list):
                    for row in rows:
                        content = row.get("content", "{}")
                        try:
                            results.append(json.loads(content))
                        except Exception:
                            results.append({"raw": str(content)[:LOG_TRUNC_200]})
            except Exception:
                logger.debug("answer_aggregator: answer aggregate failed")

        return results

    # ── Dedup ──────────────────────────────────────────────────

    def _dedup(self, answers: list[dict]) -> dict[str, list[str]]:
        """Group answers by fingerprint. Returns fingerprint → cell_id list."""
        groups: dict[str, list[str]] = defaultdict(list)
        for a in answers:
            fp = a.get("fingerprint", "") or a.get("content", "").__str__()
            cell_id = a.get("cell_id", "?")
            groups[fp].append(cell_id)
        # Only return groups with duplicates
        return {fp: cells for fp, cells in groups.items() if len(cells) > 1}

    # ── Coverage ───────────────────────────────────────────────

    def _check_coverage(self, answers: list[dict]) -> dict:
        """Check which issues each cell answered."""
        by_cell: dict[str, set[str]] = defaultdict(set)
        by_issue: dict[str, set[str]] = defaultdict(set)

        for a in answers:
            cell = a.get("cell_id", "?")
            content = a.get("content", {})
            if isinstance(content, dict):
                answer_text = content.get("answer", "")
                fingerprint = hashlib_md5(answer_text[:LOG_TRUNC_100])
                by_cell[cell].add(fingerprint)
                by_issue[fingerprint].add(cell)

        all_fingerprints = set()
        for s in by_cell.values():
            all_fingerprints.update(s)

        uncovered = [fp for fp in all_fingerprints if len(by_issue.get(fp, set())) < len(by_cell)]

        return {
            "total_cells": len(by_cell),
            "total_issues": len(all_fingerprints),
            "unanswered_issues": [(fp, list(by_issue.get(fp, set()))) for fp in uncovered],
            "cell_coverage": {c: len(fps) for c, fps in by_cell.items()},
        }

    # ── Divergence detection ──────────────────────────────────

    def _find_divergences(self, answers: list[dict]) -> list[dict]:
        """Detect divergences: same topic, conflicting positions."""
        divergences: list[dict] = []

        # Group answers by type
        by_type = defaultdict(list)
        for a in answers:
            at = a.get("answer_type", "answer")
            by_type[at].append(a)

        for atype, group in by_type.items():
            if len(group) < 2:
                continue
            # Simple heuristic: compare answer lengths and positions
            positions = [g.get("content", {}).get("answer", "")[:LOG_TRUNC_100] for g in group]
            if len(set(positions)) >= 2:
                divergences.append(
                    {
                        "topic": atype,
                        "cells": list({a.get("cell_id", "?") for a in group}),
                        "positions": [
                            {
                                "cell": a.get("cell_id", "?"),
                                "summary": a.get("content", {}).get("answer", "")[:LOG_TRUNC_100],
                            }
                            for a in group
                        ],
                        "severity": "high" if len(set(positions)) >= 3 else "medium",
                    }
                )

        return divergences

    # ── Consistency ────────────────────────────────────────────

    def _find_consistency(self, answers: list[dict], dedup_map: dict[str, list[str]]) -> list[dict]:
        """Identify consistent (agreed) answers across cells."""
        consistent = []
        for fp, cells in dedup_map.items():
            if len(cells) >= 2:
                consistent.append(
                    {
                        "fingerprint": fp,
                        "cells": cells,
                        "consensus": True,
                    }
                )
        return consistent

    # ── Supplement extraction ─────────────────────────────────

    def _extract_supplements(self, answers: list[dict]) -> list[dict]:
        """Extract supplement issues from all answers."""
        supplements = []
        for a in answers:
            if a.get("answer_type") == "supplement":
                content = a.get("content", {})
                answer_text = content.get("answer", "")
                if answer_text:
                    supplements.append(
                        {
                            "source_cell": a.get("cell_id", "?"),
                            "source_agent": a.get("agent_id", ""),
                            "title": answer_text[:LOG_TRUNC_80],
                            "description": answer_text[:LOG_TRUNC_500],
                        }
                    )
        # Dedup by title similarity
        seen_titles = set()
        unique = []
        for s in supplements:
            title = s["title"].lower().strip()
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique.append(s)
        return unique

    # ── Merge ─────────────────────────────────────────────────

    def _merge(self, answers: list[dict]) -> dict:
        """Build a merged answer from all cells."""
        all_texts = []
        for a in answers:
            content = a.get("content", {})
            if isinstance(content, dict):
                text = content.get("answer", "")
                if text:
                    all_texts.append(f"[{a.get('cell_id', '?')}] {text[:LOG_TRUNC_200]}")
        return {
            "merged_text": "\n".join(all_texts[:20]),
            "source_cells": list({a.get("cell_id", "?") for a in answers}),
            "total_answers": len(answers),
        }


def hashlib_md5(text: str) -> str:
    """Return a truncated md5 hex digest of *text*."""
    import hashlib

    return hashlib.md5(text.encode()).hexdigest()[:HASH_TRUNC_LONG]
