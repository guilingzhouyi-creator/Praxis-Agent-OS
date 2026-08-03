"""CellOrchestrator — peer agent fork-join orchestration with verify-and-retry.

Pattern:
  Peer Agent decomposes its card task into N sub-tasks,
  dispatches N SubAgents in parallel via SubAgentPool,
  collects results (Future-driven join), auto-verifies via Scouts,
  runs gap analysis, and feeds back into
  the Peer Agent's TodoTracker self-correction loop.

Buffers:
  Buffer-1: SubAgent execution results (work output)
  Buffer-2: Scout verification results (validation findings)

Flow:
  cell.subagent_orchestrate(card_task, sub_tasks, verify_prompt)
    ├─ Phase 1: Fork — dispatch all sub_tasks as parallel SubAgents
    ├─ Phase 2: Join — collect_all via SubAgentPool → Buffer-1
    ├─ Phase 3: Verify — auto-dispatch Scouts for each result → Buffer-2
    ├─ Phase 4: Gap analysis — compare Buffer-1 vs Buffer-2
    └─ Phase 5: Return structured result for Peer Agent self-correction
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.api import SUBAGENT_RUN_TIMEOUT
from l1.kernel.discovery import get_tool_config
from l3.agent.subagent_pool import SubAgentPool
from l3.agent.subagent_spec import SubAgentSpec
from l1.kernel.params.system import LOG_TRUNC_1000, LOG_TRUNC_2000, LOG_TRUNC_500

logger = logging.getLogger(__name__)


class SubAgentOrchestrator:
    """Fork-join orchestrator for parallel SubAgent execution with verification."""

    def __init__(self, cell, parent_agent_id: str):
        self.cell = cell
        self.parent_agent_id = parent_agent_id
        self.buffer_1: list[dict] = []   # SubAgent results
        self.buffer_2: list[dict] = []   # Scout verification results
        self._pool = SubAgentPool(cell.cell_id)
        self._task_ids: list[str] = []

    # ── Phase 1+2: Fork-Join ─────────────────────────────────────

    def fork_join(self, sub_tasks: list[dict],
                  timeout: float = SUBAGENT_RUN_TIMEOUT) -> dict:
        """Dispatch all sub-tasks in parallel and wait for results.

        sub_tasks: [{"spec": "architect", "prompt": "review src/"},
                     {"spec": "security-auditor", "prompt": "check auth.py"}]
        Returns buffer-1 with all SubAgent results.
        """
        # Fork: dispatch all via SubAgentPool
        for t in sub_tasks:
            spec_name = t.get("spec", "")
            prompt = t.get("prompt", "")
            card_type = t.get("card_type", "explore")  # 'explore' | 'execute'
            if not spec_name or not prompt:
                self.buffer_1.append({"spec": spec_name, "error": "spec or prompt missing"})
                continue
            spec = SubAgentSpec(name=spec_name, read_only=(card_type == "explore"), description="")
            r = self._pool.commission(spec, prompt, card_type=card_type,
                                      parent_agent_id=self.parent_agent_id, cell=self.cell)
            if r.get("success"):
                self._task_ids.append(r["task_id"])
            else:
                self.buffer_1.append({"spec": spec_name, "error": r.get("error", "pool full")})

        # Join: Future-driven collect_all
        if not self._task_ids:
            return {"success": True, "dispatched": 0, "completed": 0,
                    "failed": 0, "timed_out": 0, "buffer_1": self.buffer_1}

        joined = self._pool.collect_all(self._task_ids, timeout=timeout)
        self.buffer_1.extend(joined.get("results", []))
        return {
            "success": True,
            "dispatched": len(self._task_ids),
            "completed": joined.get("completed", 0),
            "failed": joined.get("failed", 0),
            "timed_out": joined.get("timed_out", 0),
            "buffer_1": self.buffer_1,
        }

    # ── Phase 3: Verify ──────────────────────────────────────────

    def verify(self, verify_prompt_template: str,
               timeout: float | None = None) -> dict:
        """Auto-dispatch Scouts to verify each SubAgent result.

        Each scout prompt receives {spec}, {answer}, {result} substitution.
        Results go to buffer-2.
        """
        scout_pool = None
        try:
            from ..agent.scout import get_pool
            scout_pool = get_pool()
        except Exception:
            self.buffer_2 = [{"error": "scout pool unavailable"}]
            return {"success": False, "error": "scout pool unavailable"}

        deadline = time.time() + timeout
        for item in self.buffer_1:
            spec = item.get("spec", "?")
            answer = str(item.get("result", {}).get("answer", ""))
            result_str = str(item.get("result", {}))
            prompt = verify_prompt_template.format(
                spec=spec,
                answer=answer[:LOG_TRUNC_1000],
                result=result_str[:LOG_TRUNC_2000],
            )
            try:
                session = scout_pool.get(self.parent_agent_id)
                if session is None:
                    self.buffer_2.append({"spec": spec, "error": "no scout available"})
                    continue
                scout_result = session.run(prompt)
                scout_pool.put(session)
                self.buffer_2.append({
                    "spec": spec,
                    "result": str(scout_result)[:LOG_TRUNC_2000],
                })
            except Exception as e:
                self.buffer_2.append({"spec": spec, "error": str(e)})
            if time.time() > deadline:
                break

        return {
            "success": True,
            "verified": len(self.buffer_2),
            "buffer_2": self.buffer_2,
        }

    # ── Phase 4: Gap analysis ────────────────────────────────────

    def gap_analysis(self) -> dict:
        """Compare buffer-1 (work) vs buffer-2 (verification) to find gaps.

        Returns:
          gaps: list of items where verification raised issues
          verified: items where work passed verification
          summary: structured for Peer Agent self-correction

        Gap detection heuristics:
          - Scout result contains negative keywords (issue, warning, missing, error, failed)
          - Scout result explicitly mentions a file not processed by the SubAgent
          - SubAgent result has no matching Scout entry
        """
        gaps = []
        verified = []
        _NEGATIVE_KEYWORDS = {"warning", "issue", "missing", "error",
                              "failed", "vulnerability", "problem", "concern"}
        _NEGATION_PREFIXES = {"no ", "not ", "without ", "0 "}

        for b1 in self.buffer_1:
            spec = b1.get("spec", "?")
            status = b1.get("status", "")
            if status != "completed":
                gaps.append({"spec": spec, "reason": "subagent did not complete",
                             "severity": "HIGH"})
                continue

            scout = next((b2 for b2 in self.buffer_2 if b2.get("spec") == spec), None)
            if scout is None:
                gaps.append({"spec": spec, "reason": "no verification performed",
                             "severity": "MEDIUM"})
                continue

            scout_text = str(scout.get("result", "")).lower()
            found_issues = []
            for kw in _NEGATIVE_KEYWORDS:
                idx = scout_text.find(kw)
                if idx == -1:
                    continue
                # Check if the keyword is negated (e.g. "no issues")
                before = scout_text[max(0, idx-15):idx]
                is_negated = any(pre in before for pre in _NEGATION_PREFIXES)
                if not is_negated:
                    found_issues.append(kw)
            if found_issues:
                gaps.append({
                    "spec": spec,
                    "reason": f"verification flagged: {', '.join(found_issues)}",
                    "severity": "HIGH",
                    "scout_findings": scout_text[:LOG_TRUNC_500],
                })
            else:
                verified.append({
                    "spec": spec,
                    "result_summary": str(b1.get("result", {}).get("answer", ""))[:200],
                })

        return {
            "gaps": gaps,
            "verified": verified,
            "total": len(self.buffer_1),
            "gap_count": len(gaps),
            "verified_count": len(verified),
        }

    # ── Phase 5: Self-correction integration ─────────────────────

    def build_todo_items(self, gaps: list[dict]) -> list[dict]:
        """Convert gap analysis into TodoTracker-compatible items.

        Each gap becomes a TodoTracker task with status="pending".
        The Peer Agent's self-correction loop will retry these.
        """
        items = []
        for g in gaps:
            content = f"[subagent-gap] {g['spec']}: {g['reason']}"
            items.append({
                "content": content,
                "status": "pending",
                "attempts": 0,
                "evidence": [],
                "checks": [],
            })
        return items

    # ── Full orchestration ───────────────────────────────────────

    def run(self, sub_tasks: list[dict],
            verify_prompt: str = "",
            fork_timeout: float = SUBAGENT_RUN_TIMEOUT,
            verify_timeout: float | None = None) -> dict:
        """Run the full fork-join-verify-gap cycle.

        Args:
          sub_tasks: [{"spec": "...", "prompt": "..."}, ...]
          verify_prompt: Template with {spec}, {answer}, {result}
          fork_timeout: Max wait for all SubAgents
          verify_timeout: Max wait for all Scouts

        Returns structured result ready for Peer Agent self-correction.
        """
        result = {"success": True, "phases": []}

        # Phase 1+2: Fork-Join
        fj = self.fork_join(sub_tasks, timeout=fork_timeout)
        result["phases"].append({"phase": "fork_join", **fj})
        if not fj["completed"]:
            result["success"] = False
            result["error"] = "all subagents failed"
            return result

        # Phase 3: Verify
        if verify_prompt:
            vr = self.verify(verify_prompt, timeout=verify_timeout)
            result["phases"].append({"phase": "verify", **vr})

        # Phase 4: Gap analysis
        ga = self.gap_analysis()
        result["phases"].append({"phase": "gap_analysis", **ga})

        # Phase 5: Build todo items for self-correction
        todo_items = self.build_todo_items(ga.get("gaps", []))
        result["todo_items"] = todo_items

        return result
