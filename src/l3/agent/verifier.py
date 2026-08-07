"""Self-verification + consistency checking for AgentLoop.

Layer 1 of the feedback loop:
  - Self-check: validate a tool result against the goal
  - Consistency: compare all step results for contradictions
  - Correction: generate a corrective prompt when verification fails
"""

from __future__ import annotations

import json
import logging
from typing import Any

from l1.kernel.params.agent import MAX_SELF_HEAL
from l1.kernel.params.system import LOG_TRUNC_100, LOG_TRUNC_200, LOG_TRUNC_1000
from l1.kernel.prompts import get_prompt

logger = logging.getLogger(__name__)


class Verifier:
    """Verification engine for AgentLoop results.

    Uses config-driven prompts from kernel.prompts.
    Falls back to built-in defaults if not overridden in YAML.
    """

    def __init__(self, llm_call: Any | None = None):
        self._llm_call = llm_call
        self._stats = {"checks": 0, "pass": 0, "fail": 0, "corrections": 0}

    def check(self, result: dict, goal: str) -> dict:
        """Verify a single tool result against the goal.

        Returns:
            {"pass": bool, "reason": str, "suggestions": list, "retry_allowed": bool}
        """
        self._stats["checks"] += 1
        prompt = get_prompt("verifier.self_check").format(
            goal=goal[:LOG_TRUNC_1000], result=str(result.get("output", ""))[:2000]
        )

        if self._llm_call:
            try:
                raw = self._llm_call(prompt)
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                verdict = bool(parsed.get("pass", False))
            except Exception:
                verdict = self._rule_check(result)
        else:
            verdict = self._rule_check(result)

        entry = {
            "pass": verdict,
            "reason": "" if verdict else "Rule-based check failed",
            "suggestions": [],
            "retry_allowed": self._stats.get("corrections", 0) < MAX_SELF_HEAL,
        }
        if verdict:
            self._stats["pass"] += 1
        else:
            self._stats["fail"] += 1
            logger.info("verifier: check failed (goal=%.60s)", goal)
        return entry

    def consistency_check(self, results: list[dict], goal: str = "") -> dict:
        """Check all step results for contradictions.

        Returns:
            {"consistent": bool, "conflicts": list, "recommendation": str}
        """
        if len(results) < 2:
            return {"consistent": True, "conflicts": [], "recommendation": ""}

        summary = "\n".join(
            f"Step {i}: {r.get('action', '?')} -> {str(r.get('output', ''))[:LOG_TRUNC_200]}"
            for i, r in enumerate(results)
        )
        prompt = get_prompt("verifier.consistency").format(results=summary, goal=goal[:LOG_TRUNC_1000])

        if self._llm_call:
            try:
                raw = self._llm_call(prompt)
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                return {
                    "consistent": bool(parsed.get("consistent", True)),
                    "conflicts": parsed.get("conflicts", []),
                    "recommendation": parsed.get("recommendation", ""),
                }
            except Exception:
                logger.debug("verifier: consistency check parse failed")
        return {"consistent": True, "conflicts": [], "recommendation": ""}

    def correction_prompt(self, goal: str, errors: list[str]) -> str:
        """Generate a corrective prompt when verification fails."""
        self._stats["corrections"] += 1
        return get_prompt("verifier.correction").format(
            goal=goal[:LOG_TRUNC_1000],
            errors="\n".join(errors),
        )

    def stats(self) -> dict:
        """Return verifier performance statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset verifier statistics counters."""
        self._stats = {"checks": 0, "pass": 0, "fail": 0, "corrections": 0}

    @staticmethod
    def _rule_check(result: dict) -> bool:
        """Rule-based fallback when no LLM available."""
        if result.get("success") is False:
            return False
        if result.get("error"):
            return False
        output = result.get("output", "")
        return not (
            isinstance(output, str)
            and ("error" in output.lower() or "fail" in output.lower())
            and "error" in output.lower()[:LOG_TRUNC_100]
        )
