from __future__ import annotations
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from l1.kernel.params.system import LOG_TRUNC_500

logger = logging.getLogger(__name__)

class ResultMerger:
    """Multi sub-agent result merging — conflict detection + merge summary."""

    @staticmethod
    def merge(results: list[dict]) -> dict:
        """Merge results from multiple sub-agents."""
        completed = [r for r in results if r.get("status") == "completed"]
        failed = [r for r in results if r.get("status") == "failed"]

        contents = []
        for r in completed:
            content = r.get("result", {}).get("content", "")
            if content:
                contents.append(f"=== {r.get('spec', '?')} ===\n{content[:LOG_TRUNC_500]}")

        summary = "\n\n".join(contents) if contents else "(no content)"

        # Conflict detection: when multiple sub-agents give different conclusions on the same topic
        conflicts = ResultMerger._detect_conflicts(completed)

        return {
            "success": True,
            "total": len(results),
            "completed": len(completed),
            "failed": len(failed),
            "summary": summary,
            "conflicts": conflicts,
            "has_conflicts": len(conflicts) > 0,
            "individual_results": results,
        }

    @staticmethod
    def _detect_conflicts(results: list[dict]) -> list[dict]:
        """Simple keyword-level conflict detection."""
        if len(results) < 2:
            return []

        conflicts = []
        # Compare each pair of results
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                a = results[i].get("result", {}).get("content", "")
                b = results[j].get("result", {}).get("content", "")
                if not a or not b:
                    continue

                # Check if one says "safe" and the other says "vulnerable"
                a_lower = a.lower()
                b_lower = b.lower()
                if ("safe" in a_lower and "vulnerable" in b_lower) or \
                   ("vulnerable" in a_lower and "safe" in b_lower):
                    conflicts.append({
                        "type": "verdict_conflict",
                        "between": [results[i].get("spec"), results[j].get("spec")],
                        "detail": "One says safe, the other says vulnerable",
                    })

        return conflicts
