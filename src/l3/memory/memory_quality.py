"""Memory quality heuristics — extracted from memory.py for modularity.

Auto-scores memory importance 0.0-1.0 and validates memory quality.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from l1.kernel.params.system import (
    LOG_TRUNC_2000,
    MEMORY_IMPORTANCE_BASE, MEMORY_IMPORTANCE_DECISION, MEMORY_IMPORTANCE_PATTERN,
    MEMORY_IMPORTANCE_SUMMARY, MEMORY_IMPORTANCE_OBSERVATION,
    MEMORY_MIN_CONTENT_LEN,
)

logger = logging.getLogger(__name__)

# Entry types that are always saved (tool results, decisions)
_ALWAYS_SAVE = {"decision", "pattern", "summary", "fingerprint"}

# Content patterns that indicate BAD memory (too vague or useless)
_VAGUE_PATTERNS = re.compile(
    r"(user has a project|agent note:|i have a|there is a|"
    r"python lists are|the sky is|water is wet|"
    r"^\s*\w+\s+is\s+\w+\s*$)", re.IGNORECASE
)

# Minimum content length for actionable memory
_MIN_CONTENT_LEN = MEMORY_MIN_CONTENT_LEN  # re-export alias for backward compat


def _score_importance(content: str, entry_type: str) -> float:
    """Auto-score memory importance 0.0-1.0 based on content quality.

    Criteria:
      - Entry type weight: decision/pattern > summary > observation > tool_call
      - Specificity: contains specific paths, versions, ports, names
      - Density: high info-per-char ratio
      - Actionability: contains concrete instructions or facts
    """
    base = MEMORY_IMPORTANCE_BASE

    type_bonus = {
        "decision": MEMORY_IMPORTANCE_DECISION, "pattern": MEMORY_IMPORTANCE_PATTERN,
        "summary": MEMORY_IMPORTANCE_SUMMARY,
        "observation": MEMORY_IMPORTANCE_OBSERVATION, "tool_call": 0.0,
    }
    base += type_bonus.get(entry_type, 0.0)

    specifics = 0.0
    if re.search(r"[\\/][\w.\-]+[\\/]", content):
        specifics += 0.15  # has path-like content
    if re.search(r"\b\d+\.\d+\.\d+\b", content):
        specifics += 0.1   # has version number
    if re.search(r"port\s+\d+|:\d{2,5}\b", content):
        specifics += 0.1   # has port number
    if len(content) > 100:
        specifics += 0.05  # substantive
    if len(content) > 500:
        specifics -= 0.1   # too verbose
    if len(content) < MEMORY_MIN_CONTENT_LEN:
        specifics -= 0.2

    return max(0.0, min(1.0, base + specifics))


def _is_good_memory(content: str, entry_type: str) -> tuple[bool, str]:
    """Validate memory quality. Returns (accepted, reason)."""
    if entry_type in _ALWAYS_SAVE:
        return True, ""
    if len(content) < MEMORY_MIN_CONTENT_LEN:
        return False, f"too short ({len(content)} < {MEMORY_MIN_CONTENT_LEN})"
    if _VAGUE_PATTERNS.search(content):
        return False, "vague pattern"
    if len(content) > LOG_TRUNC_2000:
        return False, "too long (>2000 chars), extract key facts instead"
    return True, ""


def _suggest_compact(entries: list) -> list[dict]:
    """Suggest entry pairs that could be merged (same agent + same tag cluster)."""
    groups: dict[str, list] = {}
    for e in entries:
        key = f"{e.agent_id}:{sorted(e.tags)[:3]}"
        groups.setdefault(key, []).append(e)

    suggestions = []
    for group in groups.values():
        if len(group) >= 3:
            total_tokens = sum(getattr(e, 'tokens', 0) or len(e.content) // 4 for e in group)
            suggestions.append({
                "entries": [e.id for e in group],
                "total_tokens": total_tokens,
                "agent_id": group[0].agent_id,
                "tags": list(set(t for e in group for t in e.tags)),
            })
    suggestions.sort(key=lambda x: x["total_tokens"], reverse=True)
    return suggestions
