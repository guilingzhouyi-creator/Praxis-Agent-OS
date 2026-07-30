"""Selector — identity selection + pre-connect verification for Direct Mode.

Flow:
  1. PreSelector: scan all Cells → collect agent rosters (PID, role, status)
  2. Selector: route by agent_id / role / territory → (cell_id, agent_id)
  3. PreConnect: verify liveness + prompt injection check → allow/deny
"""

from __future__ import annotations

import copy
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.agent import (
    INJECTION_PATTERN_ZH1,
    INJECTION_PATTERN_ZH2,
    INJECTION_HIGH_RISK_THRESHOLD,
    INJECTION_MEDIUM_RISK_THRESHOLD,
    INJECTION_REVIEW_BOOST,
    INJECTION_REVIEW_REWARD,
    INJECTION_LENGTH_THRESHOLD,
    INJECTION_LENGTH_BOOST,
)
from l1.kernel.params.system import TLB_DEFAULT_RING
from l3.error_bus import capture

logger = logging.getLogger(__name__)

# ── Role-based reverse index: role → [(cell_id, agent_id)]
# Built by preselect(), consumed by _select_best() for O(1) role lookup.
_role_index: dict[str, list[tuple[str, str]]] = {}
_role_index_stale: bool = True
_role_index_lock = threading.Lock()

# ── Known injection patterns (rule-based, expand over time) ──

# ── External LLM reviewer callback ──
# Set via set_llm_reviewer(callable). Called when preconnect detects
# medium-risk messages (0.3 < score < 0.7) for a second opinion.
_llm_reviewer: Any = None
_llm_reviewer_lock = threading.Lock()


def set_llm_reviewer(callback: Any) -> None:
    """Register an external LLM reviewer for prompt injection.

    The callback receives (message: str) and should return
    {"safe": bool, "reason": str, "confidence": float}.
    Called by preconnect() when rule-based score is inconclusive.
    """
    with _llm_reviewer_lock:
        global _llm_reviewer
        _llm_reviewer = callback
    logger.info("llm_reviewer registered")


_INJECTION_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"ignore\s+(all\s+)?(previous|above|system)\s+(instructions|prompts)", re.I), 0.5),
    (re.compile(r"forget\s+(all\s+)?(previous|above|system)", re.I), 0.5),
    (re.compile(INJECTION_PATTERN_ZH1, re.I), 0.5),
    (re.compile(r"disregard\s+(all\s+)?(previous|above)", re.I), 0.4),
    (re.compile(INJECTION_PATTERN_ZH2, re.I), 0.4),
    (re.compile(r"new\s+instructions?:?\s*$", re.I), 0.3),
    (re.compile(r"system\s+(prompt|message):", re.I), 0.2),
    (re.compile(r"<\s*system\s*>", re.I), 0.2),
    (re.compile(r"role\s*:\s*system", re.I), 0.2),
]


# ── Agent identity ──

@dataclass
class AgentIdentity:
    """Identifies a Peer Agent across Cells."""
    cell_id: str = ""
    agent_id: str = ""
    role: str = ""
    pid: int = 0
    ring: int = TLB_DEFAULT_RING
    territory: list[str] = field(default_factory=list)
    status: str = ""
    reachable: bool = False


# ── PreSelector: scan all Cells ──

def preselect() -> dict:
    """Scan all registered Cells, collect agent rosters with status.

    Returns:
        {"agents": [AgentIdentity, ...], "cells": [cell_id, ...], "total": int}
    """
    agents: list[dict] = []
    cell_ids: list[str] = []

    try:
        from .cell import get_cells
        cells = get_cells()
    except Exception as e:
        logger.warning("preselect: get_cells failed: %s", e)
        return {"agents": [], "cells": [], "total": 0, "error": "cell service unavailable"}

    for cell_id, cell in cells.items():
        cell_ids.append(cell_id)
        try:
            liveness = cell.liveness()
            for aid, ainfo in liveness.get("agents", {}).items():
                agents.append({
                    "cell_id": cell_id,
                    "agent_id": aid,
                    "role": ainfo.get("role", ainfo.get("status", "?")),
                    "status": ainfo.get("status", "unknown"),
                    "alive": ainfo.get("alive", False),
                    "territory": liveness.get("territory", []),
                })
        except Exception as e:
            logger.warning("preselect cell %s: %s", cell_id, e)
            capture("preselect cell failed", error_code="E_PRESELECT", component="l2", context={"cell_id": cell_id})

    # Build role index for O(1) subsequent lookups
    if agents:
        _rebuild_role_index(cells)

    return {"agents": agents, "cells": cell_ids, "total": len(agents)}


def _rebuild_role_index(cells: dict) -> None:
    """Build reverse index: role → [(cell_id, agent_id)] for O(1) lookup."""
    global _role_index, _role_index_stale
    idx: dict[str, list[tuple[str, str]]] = {}
    for cell_id, cell in cells.items():
        try:
            liveness = cell.liveness()
            for aid, ainfo in liveness.get("agents", {}).items():
                role = ainfo.get("role", ainfo.get("status", "?")).lower()
                idx.setdefault(role, []).append((cell_id, aid))
        except Exception as e:
            logger.warning("preselect cell %s: %s", cell_id, e)
            capture("preselect cell role_index failed", error_code="E_PRESELECT", component="l2", context={"cell_id": cell_id})
            continue
    with _role_index_lock:
        _role_index = idx
        _role_index_stale = False


# ── Selector: route to specific agent ──

def select(cell_id: str = "", agent_id: str = "",
           role: str = "", domain: str = "") -> dict:
    """Select a specific agent by cell_id + agent_id, or by role/domain.

    Returns:
        {"success": bool, "cell_id": str, "agent_id": str,
         "identity": AgentIdentity, "error": str}
    """
    if agent_id:
        return _select_by_id(agent_id)

    if cell_id:
        return _select_by_role(cell_id, role, domain)

    # Scan all cells for best match
    result = _select_best(role, domain)
    if result.get("success"):
        return result

    return {"success": False, "error": "no matching agent found"}


# ── PreConnect verification ──

def preconnect(cell_id: str, agent_id: str, message: str = "") -> dict:
    """Verify connection is healthy and message is safe before routing.

    Checks:
      1. Cell liveness
      2. Agent reachability
      3. Prompt injection (if message provided)

    Returns:
        {"allowed": bool, "reason": str, "injection_risk": float}
    """
    reasons = []
    injection_risk = 0.0

    # 1. Cell liveness
    try:
        from .cell import get_cell
        cell = get_cell(cell_id)
        liveness = cell.liveness()
        if liveness.get("overall") == "unreachable":
            return {"allowed": False, "reason": "cell_unreachable", "injection_risk": 0.0}
    except Exception as e:
        return {"allowed": False, "reason": f"cell_error: {e}", "injection_risk": 0.0}

    # 2. Agent reachability
    try:
        reachable = cell.agent_reachable(agent_id)
        if not reachable.get("reachable"):
            reasons.append(reachable.get("reason", "unreachable"))
    except Exception as e:
        reasons.append(f"agent_check: {e}")

    # 3. Prompt injection scan
    if message:
        injection_risk = _scan_injection(message)
        if injection_risk > INJECTION_HIGH_RISK_THRESHOLD:
            reasons.append("prompt_injection_suspected")
        elif injection_risk > INJECTION_MEDIUM_RISK_THRESHOLD:
            with _llm_reviewer_lock:
                reviewer = _llm_reviewer
            if reviewer:
                # Medium risk: call external LLM reviewer for second opinion
                try:
                    review = reviewer(message)
                    if not review.get("safe", False):
                        reasons.append(f"llm_review: {review.get('reason', 'unsafe')}")
                        injection_risk = min(1.0, injection_risk + INJECTION_REVIEW_BOOST)
                    else:
                        injection_risk = max(0.0, injection_risk - INJECTION_REVIEW_REWARD)
                except Exception as e:
                    logger.warning("llm_review failed: %s", e)
                    capture("llm_review failed", error_code="E_LLM_REVIEW", component="l2")

    return {
        "allowed": len(reasons) == 0,
        "reason": "; ".join(reasons) if reasons else "ok",
        "injection_risk": round(injection_risk, 2),
    }


# ── Internal ──

def _select_by_id(agent_id: str) -> dict:
    """Find an agent by ID across all Cells.  Returns {"success", "cell_id", "agent_id"}."""
    from .cell import get_cells
    for cell_id, cell in get_cells().items():
        try:
            r = cell.agent_reachable(agent_id)
            if r.get("reachable") or r.get("reason") == "in_session":
                return {
                    "success": True, "cell_id": cell_id, "agent_id": agent_id,
                }
        except Exception as e:
            logger.warning("select_by_id %s/%s: %s", cell_id, agent_id, e)
            capture("select_by_id failed", error_code="E_SELECT", component="l2", context={"cell_id": cell_id, "agent_id": agent_id})
            continue
    return {"success": False, "error": f"agent {agent_id} not found or unreachable"}


def _select_by_role(cell_id: str, role: str, domain: str) -> dict:
    from .cell import get_cell
    try:
        cell = get_cell(cell_id)
        liveness = cell.liveness()
        for aid, info in liveness.get("agents", {}).items():
            if info.get("role", info.get("status", "")).lower() == role.lower():
                return {"success": True, "cell_id": cell_id, "agent_id": aid}
    except Exception as e:
        logger.warning("select_by_role %s/%s: %s", cell_id, role, e)
        capture("select_by_role failed", error_code="E_SELECT", component="l2", context={"cell_id": cell_id, "role": role})
    return {"success": False, "error": f"no agent with role {role} in {cell_id}"}


def _select_best(role: str, domain: str) -> dict:
    global _role_index, _role_index_stale
    from .cell import get_cells
    best = None
    best_score = -1

    # Use role index for O(1) initial candidate selection
    if role:
        role_lower = role.lower()
        with _role_index_lock:
            stale = _role_index_stale
            candidates = _role_index.get(role_lower, []) if not stale else []
        if stale:
            try:
                _rebuild_role_index(get_cells())
            except Exception as e:
                logger.warning("_rebuild_role_index failed: %s", e)
                capture("_rebuild_role_index failed", error_code="E_PRESELECT", component="l2")
            with _role_index_lock:
                candidates = _role_index.get(role_lower, [])
    else:
        candidates = []

    if not candidates:
        # Fallback: scan all cells × agents (O(C×A))
        for cell_id, cell in get_cells().items():
            lv = cell.liveness()
            agents_data = lv.get("agents", {})
            cell_territory = getattr(cell, 'territory', [])
            for aid, info_dict in agents_data.items():
                score = 0
                info_role = info_dict.get("role", "")
                if role and info_role.lower() == role.lower():
                    score += 2
                if domain:
                    for t in cell_territory:
                        if domain.startswith(t):
                            score += 1
                if score > best_score:
                    best_score = score
                    best = (cell_id, aid)
    else:
        # Index hit: only score candidates matching the role
        cell_cache: dict[str, Any] = {}
        for cell_id, aid in candidates:
            if cell_id not in cell_cache:
                try:
                    cell = get_cells().get(cell_id)
                    cell_cache[cell_id] = getattr(cell, 'territory', []) if cell else []
                except Exception as e:
                    logger.warning("cell_cache territory for %s: %s", cell_id, e)
                    capture("cell_cache territory failed", error_code="E_CACHE", component="l2", context={"cell_id": cell_id})
                    cell_cache[cell_id] = []
            cell_territory = cell_cache[cell_id]
            score = 2  # role match
            if domain:
                for t in cell_territory:
                    if domain.startswith(t):
                        score += 1
            if score > best_score:
                best_score = score
                best = (cell_id, aid)

    if best:
        return {"success": True, "cell_id": best[0], "agent_id": best[1]}
    return {"success": False, "error": "no matching agent"}


def _scan_injection(message: str) -> float:
    """Scan message for prompt injection patterns. Returns risk score 0.0-1.0."""
    if not message:
        return 0.0
    score = 0.0
    for pattern, weight in _INJECTION_PATTERNS:
        if pattern.search(message):
            score += weight
    # Length heuristic: very long messages with injection-like patterns
    if len(message) > INJECTION_LENGTH_THRESHOLD and score > 0:
        score = min(1.0, score + INJECTION_LENGTH_BOOST)
    return min(1.0, score)

