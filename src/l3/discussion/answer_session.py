"""AnswerSession — three-agent ordered answer protocol within a Cell.

Each Cell runs an AnswerSession when an IssueCard arrives.  The session
proceeds through 5 ordered phases:

  Phase 1 — Answer:       Each Peer Agent answers all issues independently.
  Phase 2 — Cross-examine: Agents question each other's answers pairwise.
  Phase 3 — Supplement:   Each agent proposes supplementary issues.
  Phase 4 — Converge:     Cell consolidates answers into a composite.
  Phase 5 — Report:       Pushes CellAnswer to IssueOrchestrator.

Each phase writes a checkpoint via CellAnswerRepo for crash recovery.
If watchdog reboots an agent mid-phase, AnswerSession.recover()
returns the latest checkpoint so execution can resume.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.agent import AGENT_LOOP_DEFAULT_TIMEOUT
from l1.kernel.params.system import LOG_TRUNC_200
from l3.agent.agent_loop import AgentLoop

from .cell_answer_repo import AnswerCheckpoint, CellAnswer, CellAnswerRepo

logger = logging.getLogger(__name__)

_PHASE_NAMES = ["", "answer", "cross_examine", "supplement", "converge", "report"]


class AnswerSession:
    """Three-agent ordered answer protocol.

    Usage:
      session = AnswerSession(session_id, cell_id, cell, issue_card, repo)
      result = session.run()
    """

    def __init__(
        self,
        session_id: str,
        cell_id: str,
        cell: Any,
        issue_card: Any,
        repo: CellAnswerRepo | None = None,
    ):
        self.session_id = session_id
        self.cell_id = cell_id
        self.cell = cell
        self.issue_card = issue_card
        self.repo = repo or CellAnswerRepo(cell_id, session_id)

        # Resolve the three Peer Agents in order
        self._agent_ids = self._resolve_agents()

        self._current_phase: int = 0
        self._phase_results: dict[int, dict] = {}

    # ── Main entry point ──────────────────────────────────────

    def run(self, phase_start: int = 1) -> dict:
        """Execute the full 5-phase protocol.

        If phase_start > 1, skips completed phases (used after recovery).
        """
        self._current_phase = phase_start
        for phase in range(phase_start, 6):
            phase_name = _PHASE_NAMES[phase]
            logger.info("answer_session %s: phase %d/%d (%s)",
                        self.session_id, phase, 5, phase_name)
            try:
                result = self._execute_phase(phase)
                self._phase_results[phase] = result
            except Exception as e:
                logger.error("answer_session %s phase %d failed: %s",
                             self.session_id, phase, e)
                return {"success": False, "error": str(e), "phase": phase}

        return {"success": True, "phases": self._phase_results}

    def recover(self) -> int:
        """Read the latest checkpoint and return the phase to resume from.

        Returns 1 if no checkpoint found (start from beginning).
        """
        cp = self.repo.latest_checkpoint()
        if cp is None:
            return 1
        if cp.status == "completed":
            return cp.phase + 1  # next phase
        return cp.phase  # retry current phase

    # ── Phase execution ───────────────────────────────────────

    def _execute_phase(self, phase: int) -> dict:
        """Execute a single phase by name."""
        phase_name = _PHASE_NAMES[phase]
        return getattr(self, f"_phase_{phase_name}")()

    def _phase_answer(self) -> dict:
        """Phase 1: All three agents answer all issues independently."""
        cp = self.repo.latest_checkpoint()
        completed = cp.completed_agents if cp and cp.phase == 1 else []
        results = []
        for agent_id in self._agent_ids:
            if agent_id in completed:
                continue
            answer = self._agent_answer(agent_id)
            r = self.repo.store_answer(answer)
            results.append(r)
            completed.append(agent_id)
            self.repo.save_checkpoint(AnswerCheckpoint(
                session_id=self.session_id,
                phase=1, phase_name="answer",
                completed_agents=list(completed),
                pending_agents=[a for a in self._agent_ids if a not in completed],
            ))
        return {"success": True, "answers": len(results)}

    def _phase_cross_examine(self) -> dict:
        """Phase 2: Pairwise cross-examination.

        Each agent questions the other two about their answers.
        """
        cp = self.repo.latest_checkpoint()
        completed = cp.completed_agents if cp and cp.phase == 2 else []
        results = []
        for examiner in self._agent_ids:
            if examiner in completed:
                continue
            for target in self._agent_ids:
                if target == examiner:
                    continue
                exam = self._agent_examine(examiner, target)
                if exam:
                    r = self.repo.store_answer(exam)
                    results.append(r)
            completed.append(examiner)
            self.repo.save_checkpoint(AnswerCheckpoint(
                session_id=self.session_id,
                phase=2, phase_name="cross_examine",
                completed_agents=list(completed),
                pending_agents=[a for a in self._agent_ids if a not in completed],
            ))
        return {"success": True, "examinations": len(results)}

    def _phase_supplement(self) -> dict:
        """Phase 3: Each agent proposes supplementary issues."""
        cp = self.repo.latest_checkpoint()
        completed = cp.completed_agents if cp and cp.phase == 3 else []
        results = []
        for agent_id in self._agent_ids:
            if agent_id in completed:
                continue
            supp = self._agent_supplement(agent_id)
            if supp:
                r = self.repo.store_answer(supp)
                results.append(r)
            completed.append(agent_id)
            self.repo.save_checkpoint(AnswerCheckpoint(
                session_id=self.session_id,
                phase=3, phase_name="supplement",
                completed_agents=list(completed),
                pending_agents=[a for a in self._agent_ids if a not in completed],
                supplement_count=len(results),
            ))
        return {"success": True, "supplements": len(results)}

    def _phase_converge(self) -> dict:
        """Phase 4: Consolidate all answers into a composite cell answer."""
        all_answers = self.repo.get_all()
        composite_answer = CellAnswer(
            cell_id=self.cell_id,
            session_id=self.session_id,
            agent_id="system",
            phase=4,
            answer_type="resolution",
            content={
                "cell_id": self.cell_id,
                "total_answers": len(all_answers),
                "summary": self._build_summary(all_answers),
            },
        )
        r = self.repo.store_answer(composite_answer)
        self.repo.save_checkpoint(AnswerCheckpoint(
            session_id=self.session_id,
            phase=4, phase_name="converge",
            status="completed",
            completed_agents=list(self._agent_ids),
        ))
        return {"success": True, **r}

    def _phase_report(self) -> dict:
        """Phase 5: Push results to IssueOrchestrator."""
        all_answers = self.repo.get_all()
        supplements = [a for a in all_answers if a.answer_type == "supplement"]
        # Notify IssueOrchestrator via Cell bus
        try:
            self.cell._cell_bus.emit("discussion.cell_complete", {
                "session_id": self.session_id,
                "cell_id": self.cell_id,
                "answer_count": len(all_answers),
                "supplement_count": len(supplements),
            })
        except Exception as e:
            logger.warning("answer_session: report emit failed: %s", e)
        self.repo.save_checkpoint(AnswerCheckpoint(
            session_id=self.session_id,
            phase=5, phase_name="report",
            status="completed",
            completed_agents=list(self._agent_ids),
        ))
        return {"success": True, "answers": len(all_answers)}

    # ── Agent interaction helpers ─────────────────────────────

    def _resolve_agents(self) -> list[str]:
        """Resolve the three Peer Agents from the Cell."""
        try:
            return sorted(self.cell._agents.keys())[:3]
        except Exception:
            return ["agent-a", "agent-b", "agent-c"]

    def _agent_answer(self, agent_id: str) -> CellAnswer:
        """Ask agent to answer all issues via AgentLoop."""
        issues = getattr(self.issue_card, "items", [])
        items_text = "\n".join(
            f"{i.id}: {i.question} (domain: {i.domain})"
            for i in issues
        )
        prompt = (
            f"Answer the following issues for your territory.\n\n"
            f"Cell: {self.cell_id}\n"
            f"Issues:\n{items_text}\n\n"
            f"For each issue, provide:\n"
            f"- position: your stance\n"
            f"- reasoning: why you hold this position\n"
            f"- evidence: relevant facts or references"
        )
        result = self._run_agent_loop(agent_id, prompt)
        return CellAnswer(
            cell_id=self.cell_id, session_id=self.session_id,
            agent_id=agent_id, phase=1, answer_type="answer",
            content=result,
        )

    def _agent_examine(self, examiner: str, target: str) -> CellAnswer | None:
        """Ask examiner to question target's answers."""
        target_answers = self.repo.get_answers(phase=1)
        target_content = [
            a.content for a in target_answers if a.agent_id == target
        ]
        if not target_content:
            return None
        prompt = (
            f"You are {examiner}. Review the answers from {target}.\n\n"
            f"{target}'s answers:\n{target_content}\n\n"
            f"Cross-examine: identify gaps, inconsistencies, or areas "
            f"that need clarification."
        )
        result = self._run_agent_loop(examiner, prompt)
        return CellAnswer(
            cell_id=self.cell_id, session_id=self.session_id,
            agent_id=examiner, phase=2, answer_type="examination",
            content=result,
        )

    def _agent_supplement(self, agent_id: str) -> CellAnswer | None:
        """Ask agent to propose supplementary issues."""
        prompt = (
            "Review the discussion so far.\n\n"
            "Are there any NEW issues or questions that should be raised?\n"
            "Consider:\n"
            "- Gaps in the original issues\n"
            "- Questions that need cross-cell coordination\n"
            "- Topics that require human decision\n\n"
            "Return a list of new issues with: title, description, domain."
        )
        result = self._run_agent_loop(agent_id, prompt)
        content = result.get("answer", "")
        if not content or len(content.strip()) < 20:
            return None
        return CellAnswer(
            cell_id=self.cell_id, session_id=self.session_id,
            agent_id=agent_id, phase=3, answer_type="supplement",
            content=result,
        )

    def _run_agent_loop(self, agent_id: str, prompt: str) -> dict:
        """Run an AgentLoop for a single agent."""
        loop = AgentLoop(
            task=prompt,
            agent_id=agent_id,
            cell_id=self.cell_id,
        )
        result = loop.run(max_steps=5, timeout=AGENT_LOOP_DEFAULT_TIMEOUT)
        return {
            "answer": result.get("answer", ""),
            "steps": result.get("steps", []),
        }

    def _build_summary(self, answers: list[CellAnswer]) -> str:
        """Build a text summary from all answers."""
        parts = []
        for a in answers:
            text = a.content.get("answer", str(a.content)[:LOG_TRUNC_200])
            parts.append(f"[{a.agent_id}/{a.answer_type}] {text[:LOG_TRUNC_200]}")
        return "\n".join(parts)
