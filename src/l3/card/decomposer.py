"""L3 Card Decomposer — General Assembly mode: intent → multi-card split → dispatch → converge.

Pipeline:
  1. L3A parses human intent → TaskCard
  2. Decomposer splits → N sub-cards by territory
  3. Display in transaction panel → human confirmation
  4. Dispatch to Cell → execute → cross-review → converge
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import (
    DECOMPOSER_AGENT_PREFIX,
    DECOMPOSER_DEFAULT_ACTION,
    DECOMPOSER_DEFAULT_PHASE,
    DECOMPOSER_EVENT_DECOMPOSED,
    DECOMPOSER_FALLBACK_AGENT,
    DECOMPOSER_FALLBACK_ROLE,
    DECOMPOSER_ID_LENGTH,
    DECOMPOSER_L3_TARGET,
    DECOMPOSER_PLAN_PREFIX,
    DECOMPOSER_SCOUT_POOL,
    DECOMPOSER_SCOUT_ROLE,
    DECOMPOSER_SENDER,
    TERRITORY_MAP,
)
from l1.kernel.params.system import LOG_TRUNC_60

from .card_builder import build_card as _build_card
from .card_unified import CardPhase, CardSummary, CardTask, CardUnified

logger = logging.getLogger(__name__)


class DecomposeState(Enum):
    """DecomposeState — enum of DRAFT, CONFIRMED, DISPATCHED, RUNNING...."""

    DRAFT = auto()  # freshly decomposed, awaiting confirmation
    CONFIRMED = auto()  # human confirmed
    DISPATCHED = auto()  # dispatched to Cell
    RUNNING = auto()  # executing
    REVIEWING = auto()  # cross-review in progress
    CONVERGED = auto()  # converged
    FAILED = auto()  # failed


@dataclass
class CardSlice:
    """A sub-card — work unit assigned to one Agent or SubAgent pool."""

    card: CardUnified
    role: str
    agent_id: str
    territory: str
    state: DecomposeState = DecomposeState.DRAFT
    result: dict = field(default_factory=dict)
    error: str = ""
    parallelism: int = 1  # desired SubAgent parallelism
    subagent_spec: str = ""  # SubAgentSpec name for pool dispatch


@dataclass
class DecomposePlan:
    """Decompose plan — N sub-cards from one intent + convergence metadata."""

    id: str
    intent: str
    domain: str
    slices: list[CardSlice]
    state: DecomposeState = DecomposeState.DRAFT
    created_at: float = field(default_factory=time.time)
    confirmed_at: float = 0.0
    converged_at: float = 0.0

    @property
    def total_slices(self) -> int:
        return len(self.slices)

    @property
    def completed_slices(self) -> int:
        return sum(1 for s in self.slices if s.state in (DecomposeState.CONVERGED,))

    @property
    def failed_slices(self) -> int:
        return sum(1 for s in self.slices if s.state == DecomposeState.FAILED)


class Decomposer:
    """L3 Card Decomposer — General Assembly mode engine.

    One intent in:
    1. detect_card_type() → identify card type (build/fix/refactor/feature)
    2. decompose(plan) → split by territory into sub-cards
    3. confirm(plan) → human confirmation
    4. dispatch(plan) → dispatch to Cell
    5. converge(plan) → collect results, converge
    """

    def __init__(self):
        self._plans: dict[str, DecomposePlan] = {}

    def decompose(self, intent: str, domain: str = "") -> DecomposePlan:
        """Decompose: intent → sub-cards by territory."""
        plan_id = f"{DECOMPOSER_PLAN_PREFIX}{uuid.uuid4().hex[:DECOMPOSER_ID_LENGTH]}"
        base_card = _build_card(plan_id, intent, domain)

        slices: list[CardSlice] = []
        seen_roles: set[str] = set()

        for prefix, role in TERRITORY_MAP.items():
            if domain and not (domain.startswith(prefix) or prefix.startswith(domain)):
                continue
            if role in seen_roles:
                continue
            seen_roles.add(role)

            # Extract tasks belonging to this role (CardUnified phases have .tasks)
            tasks_for_role = []
            for phase in base_card.phases:
                for task in phase.tasks:
                    if task.agent == role or task.agent == DECOMPOSER_SCOUT_ROLE:
                        tasks_for_role.append(task)

            if not tasks_for_role:
                tasks_for_role = [
                    CardTask(
                        action=DECOMPOSER_DEFAULT_ACTION,
                        target=f"work on {domain}",
                        agent=role,
                        params={"prompt": f"Process {intent} for {prefix}"},
                    )
                ]

            slice_card = CardUnified(
                id=f"{plan_id}-{role}",
                priority=base_card.priority,
                nature=base_card.nature,
                phases=[CardPhase(name=f"{role}_work", tasks=tasks_for_role)],
            )
            slice_card.summary = CardSummary(
                title=intent,
                description="",
                columns={"domain": prefix},
            )
            agent_id = f"{DECOMPOSER_AGENT_PREFIX}{role}"
            slices.append(CardSlice(card=slice_card, role=role, agent_id=agent_id, territory=prefix))

        # No matching territory — create default sub-card
        if not slices:
            slice_card = CardUnified(
                id=f"{plan_id}-default",
                priority=5,
                nature="execution",
                phases=[
                    CardPhase(
                        name=DECOMPOSER_DEFAULT_PHASE,
                        tasks=[
                            CardTask(
                                action=DECOMPOSER_DEFAULT_ACTION,
                                target=intent,
                                agent=DECOMPOSER_FALLBACK_ROLE,
                                params={"prompt": intent},
                            ),
                        ],
                    )
                ],
            )
            slice_card.summary = CardSummary(title=intent, description="", columns={"domain": domain or "."})
            slices.append(
                CardSlice(
                    card=slice_card,
                    role=DECOMPOSER_FALLBACK_ROLE,
                    agent_id=DECOMPOSER_FALLBACK_AGENT,
                    territory=domain or ".",
                )
            )

        plan = DecomposePlan(id=plan_id, intent=intent, domain=domain, slices=slices)
        self._plans[plan_id] = plan

        logger.info("decomposed: %s → %d slices for roles %s", plan_id, len(slices), list(seen_roles))
        emit_signal(
            EVENT_TASK_ASSIGN,
            sender=DECOMPOSER_SENDER,
            target=DECOMPOSER_L3_TARGET,
            data={
                "plan_id": plan_id,
                "intent": intent[:LOG_TRUNC_60],
                "slices": len(slices),
                "event": DECOMPOSER_EVENT_DECOMPOSED,
            },
        )
        return plan

    def confirm(self, plan_id: str) -> dict:
        """Human confirms the decompose plan."""
        plan = self._plans.get(plan_id)
        if not plan:
            return {"success": False, "error": f"plan not found: {plan_id}"}
        plan.state = DecomposeState.CONFIRMED
        plan.confirmed_at = time.time()
        for s in plan.slices:
            s.state = DecomposeState.CONFIRMED
        logger.info("plan confirmed: %s", plan_id)
        return {"success": True, "plan_id": plan_id}

    def dispatch_to_cell(self, plan_id: str, cell: Any, agent_map: dict[str, str] | None = None) -> dict:
        """Dispatch to Cell for execution."""
        plan = self._plans.get(plan_id)
        if not plan:
            return {"success": False, "error": f"plan not found: {plan_id}"}
        if plan.state != DecomposeState.CONFIRMED:
            return {"success": False, "error": f"plan not confirmed: {plan.state.name}"}

        plan.state = DecomposeState.DISPATCHED
        results = []
        for s in plan.slices:
            if s.state == DecomposeState.FAILED:
                continue
            try:
                map_for_slice = agent_map or {s.role: s.agent_id, DECOMPOSER_SCOUT_ROLE: DECOMPOSER_SCOUT_POOL}
                r = cell.execute_card(s.card, agent_map=map_for_slice)
                s.result = r
                s.state = DecomposeState.RUNNING
                results.append(r)
            except Exception as e:
                s.state = DecomposeState.FAILED
                s.error = str(e)

        return {"success": True, "plan_id": plan_id, "results": results}

    def converge(self, plan_id: str) -> dict:
        """Converge: collect all sub-card results, check completion."""
        plan = self._plans.get(plan_id)
        if not plan:
            return {"success": False, "error": f"plan not found: {plan_id}"}

        all_done = True
        errors = []
        for s in plan.slices:
            if s.state == DecomposeState.FAILED:
                all_done = False
                errors.append(f"{s.role}: {s.error}")
            elif s.state != DecomposeState.RUNNING:
                all_done = False

        if not all_done:
            return {
                "success": False,
                "plan_id": plan_id,
                "done": plan.completed_slices,
                "total": plan.total_slices,
                "errors": errors,
            }

        plan.state = DecomposeState.CONVERGED
        plan.converged_at = time.time()
        logger.info("converged: %s (%d/%d slices)", plan_id, plan.completed_slices, plan.total_slices)
        emit_signal(
            EVENT_TASK_ASSIGN,
            sender=DECOMPOSER_SENDER,
            target=DECOMPOSER_L3_TARGET,
            data={"plan_id": plan_id, "event": "converged"},
        )
        return {"success": True, "plan_id": plan_id, "slices": plan.total_slices, "converged": True}

    def get_plan(self, plan_id: str) -> DecomposePlan | None:
        """Return the plan with the given ID, or None if not found."""
        return self._plans.get(plan_id)

    def list_plans(self, limit: int = 20) -> list[dict]:
        """Return the most recent plans as summaries, newest first."""
        return [
            {
                "id": p.id,
                "intent": p.intent[:LOG_TRUNC_60],
                "domain": p.domain,
                "state": p.state.name,
                "slices": p.total_slices,
                "done": p.completed_slices,
                "failed": p.failed_slices,
                "created_at": p.created_at,
            }
            for p in sorted(self._plans.values(), key=lambda x: x.created_at, reverse=True)[:limit]
        ]


_decomposer: Decomposer | None = None


def get_decomposer() -> Decomposer:
    """Return the global Decomposer singleton, creating it if needed."""
    global _decomposer
    if _decomposer is None:
        _decomposer = Decomposer()
    return _decomposer


def reset_decomposer() -> None:
    """Reset the Decomposer singleton to None."""
    global _decomposer
    _decomposer = None
