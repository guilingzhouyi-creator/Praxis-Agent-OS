"""Execution verify utilities — scout verification + diff logic.

Extracted from execution_plan.py for modularity.
"""

from __future__ import annotations

from typing import Any


def execute_scout_verify(ps: Any, spec: dict, phase: str) -> dict:
    """Run a scout investigation for verification (before/after)."""
    from .scout import get_pool
    pool = get_pool()
    template = spec.get("template", "grep")
    scope = spec.get("scope", {})
    scope.setdefault("path", ".")
    scope.setdefault("pattern", ps.target)
    result = pool.commission("verify", template, scope)
    return {"success": result.get("success", False),
            "findings": result.get("findings", []),
            "output": result.get("output", []),
            "phase": phase}


def diff_verify(before: dict, after: dict) -> dict:
    """Diff before vs after verification results."""
    b_findings = set(str(f) for f in before.get("findings", []))
    a_findings = set(str(f) for f in after.get("findings", []))
    return {
        "pass": a_findings != b_findings,
        "new": list(a_findings - b_findings),
        "resolved": list(b_findings - a_findings),
        "unchanged": list(b_findings & a_findings),
        "before_count": len(b_findings),
        "after_count": len(a_findings),
    }


def execute_scout(ps: Any) -> dict:
    """Execute a scout step via ScoutPool."""
    from .scout import get_pool
    pool = get_pool()
    pattern = ps.params.get("pattern", ps.target)
    path = ps.params.get("path", ".")
    task = f"Search for pattern '{pattern}' in {path}. Report all matches with file paths and line numbers."
    result = pool.commission("execution_plan", task)
    return {
        "success": result.get("success", False),
        "output": result.get("output", []),
        "findings": result.get("findings", []),
        "error": result.get("error", ""),
    }
