"""Execution verify utilities — scout verification + diff logic.

Extracted from execution_plan.py for modularity.
"""

from __future__ import annotations

from typing import Any
from l1.kernel.params.system import LOG_TRUNC_200


def execute_scout_verify(ps: Any, spec: dict, phase: str) -> dict:
    """Run a scout investigation for verification (before/after)."""
    from .agent.scout import get_pool
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
    from .agent.scout import get_pool
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


class Verifier:
    """Verification agent — check results against goals, detect inconsistencies.

    Used by ExecutionPlan for self-check and consistency verification.
    """

    def check(self, result: dict, goal: str) -> dict:
        """Check if a result satisfies a goal.

        Args:
            result: The step result dict.
            goal: Description of what was expected.

        Returns:
            Dict with pass/fail, reason, and suggestions.
        """
        passed = result.get("success", False)
        return {
            "pass": passed,
            "reason": "Goal met" if passed else f"Failed to achieve: {goal[:LOG_TRUNC_200]}",
            "suggestions": [] if passed else ["Review the error and retry"],
        }

    def consistency_check(self, results: list[dict], goal: str) -> dict:
        """Check multiple results for consistency.

        Args:
            results: List of step result dicts.
            goal: Description of what was expected.

        Returns:
            Dict with consistent flag, conflicts, and recommendation.
        """
        successes = [r for r in results if r.get("success")]
        failures = [r for r in results if not r.get("success")]
        return {
            "consistent": len(failures) == 0,
            "conflicts": [r.get("error", "unknown error") for r in failures],
            "recommendation": "All steps passed" if not failures
                             else f"{len(failures)} step(s) failed — review and retry",
        }
