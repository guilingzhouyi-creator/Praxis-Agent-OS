"""CellSubAgentMixin — subagent orchestration and dispatch.

Delegates SubAgent work to the SubAgentOrchestrator (fork-join + scout
verify) and the Cell's SubAgentPool (single-task dispatch). Composed by
Cell.
"""

from __future__ import annotations

import logging

from l1.kernel.params.agent import AGENT_LOOP_DEFAULT_TIMEOUT
from l1.kernel.params.system import SUBAGENT_ORCHESTRATE_VERIFY_TIMEOUT
from l3.services.cell_orchestrate import SubAgentOrchestrator

logger = logging.getLogger(__name__)


class CellSubAgentMixin:
    """SubAgent fork-join orchestration + single-task pool dispatch."""

    def subagent_orchestrate(
        self,
        sub_tasks: list[dict],
        parent_agent_id: str = "",
        verify_prompt: str = "",
        fork_timeout: float = AGENT_LOOP_DEFAULT_TIMEOUT,
        verify_timeout: float = SUBAGENT_ORCHESTRATE_VERIFY_TIMEOUT,
    ) -> dict:
        """Full fork-join orchestration: SubAgents + Scout verify + gap analysis.

        sub_tasks: [{"spec": "architect", "prompt": "review src/"},
                    {"spec": "security-auditor", "prompt": "check auth.py"}]
        verify_prompt: Scout prompt template ({spec}, {answer}, {result})

        Returns structured result with:
          - phases[].buffer_1  — SubAgent work results
          - phases[].buffer_2  — Scout verification results
          - phases[].gap_analysis — gaps vs verified
          - todo_items — TodoTracker-compatible self-correction items

        The Peer Agent should feed todo_items into its TodoTracker
        and let the AgentLoop's self-correction mechanism retry gaps.
        """
        orch = SubAgentOrchestrator(self, parent_agent_id)
        return orch.run(sub_tasks, verify_prompt, fork_timeout, verify_timeout)

    def subagent_dispatch_from_text(self, text: str, parent_agent_id: str = "") -> dict:
        """Parse @mention from text and dispatch via SubAgentPool."""
        return self._subagent_pool.dispatch_from_text(
            text,
            parent_agent_id,
            cell=self,
        )

    def subagent_dispatch(
        self,
        spec: str,
        prompt: str,
        parent_agent_id: str = "",
        post_actions: list | None = None,
        card_type: str = "explore",
    ) -> dict:
        """Dispatch a single SubAgent task via the Cell's SubAgentPool.

        Documented in cell-agent.md — dispatches a SubAgent (read-only for
        ``card_type="explore"``), runs it in the pool's own worker, and
        returns the task id for later collection via ``pool.collect()``.

        ``post_actions`` is accepted for API compatibility; post-dispatch
        actions are executed by the pool/orchestrator pipeline.
        """
        from l3.agent.subagent_spec import SubAgentSpec

        sub_spec = SubAgentSpec(name=spec, read_only=(card_type == "explore"), description="")
        r = self._subagent_pool.commission(
            sub_spec,
            prompt,
            card_type=card_type,
            parent_agent_id=parent_agent_id,
            cell=self,
        )
        if not r.get("success"):
            return r
        return {
            "success": True,
            "task_id": r["task_id"],
            "spec": spec,
            "post_actions": post_actions or [],
        }
