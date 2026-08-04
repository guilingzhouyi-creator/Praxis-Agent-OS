"""DEPRECATED — old Card/Phase/Step/CardMode/PhaseMode, kept only as bridge.

All new code should use CardUnified (card_unified.py) instead.
This module exists solely to support ``CardUnified.to_old_card()``
until the migration to CardUnified is complete in all downstream consumers.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto

from l1.kernel.params.system import HASH_TRUNC_MEDIUM

logger = logging.getLogger(__name__)
logger.warning("DEPRECATED: import from services.card — use services.card_unified instead")


class CardMode(Enum):
    """CardMode — enum of EXECUTE, ISSUE, PARALLEL_ALL."""
    EXECUTE = auto()
    ISSUE = auto()
    PARALLEL_ALL = auto()


class PhaseMode(Enum):
    """PhaseMode — enum of SEQUENTIAL, PARALLEL."""
    SEQUENTIAL = auto()
    PARALLEL = auto()


@dataclass
class Step:
    """DEPRECATED: use CardTask instead."""
    action: str = ""
    target: str = ""
    params: dict = field(default_factory=dict)
    agent: str = ""
    depends_on: list[str] = field(default_factory=list)
    verify: dict | None = field(default=None)

    def with_agent(self, agent: str) -> Step:
        self.agent = agent
        return self


@dataclass
class Phase:
    """DEPRECATED: use CardPhase instead."""
    name: str = ""
    steps: list[Step] = field(default_factory=list)
    mode: PhaseMode = PhaseMode.SEQUENTIAL
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Card:
    """DEPRECATED: use CardUnified instead."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:HASH_TRUNC_MEDIUM])
    intent: str = ""
    domain: str = ""
    mode: CardMode = CardMode.EXECUTE
    phases: list[Phase] = field(default_factory=list)
    priority: int = 5
    sender: str = "l3"
    cell_id: str = ""
    created_at: float = field(default_factory=__import__("time").time)

    def all_steps(self) -> list[Step]:
        return [step for phase in self.phases for step in phase.steps]

    def step_count(self) -> int:
        return len(self.all_steps())

    def phase_names(self) -> list[str]:
        return [p.name for p in self.phases]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "intent": self.intent,
            "domain": self.domain,
            "mode": self.mode.name,
            "phases": [{
                "name": p.name,
                "mode": p.mode.name,
                "steps": [{
                    "action": s.action, "target": s.target,
                    "agent": s.agent, "depends_on": s.depends_on,
                } for s in p.steps],
            } for p in self.phases],
            "priority": self.priority,
            "step_count": self.step_count(),
        }


def make_card(intent: str, domain: str = "",
              steps: list[tuple[str, str, str]] | None = None,
              mode: CardMode = CardMode.EXECUTE) -> Card:
    """DEPRECATED: construct CardUnified directly instead."""
    phases = [Phase(name="work", steps=[
        Step(action=a, target=t, agent=ag) for a, t, ag in (steps or [])
    ])]
    return Card(intent=intent, domain=domain, mode=mode, phases=phases)
