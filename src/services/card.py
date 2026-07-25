"""Card — structured execution unit for Agent OS.

A Card is a work item that goes through Cell → AgentTerminal.
Unlike a simple action+target, a Card has:
  - Phases (ordered groups of steps)
  - Steps (individual actions with routing)
  - Pipeline (agent assignments)
  - Mode (EXECUTE / ISSUE)

Card decomposition:
  Raw intent (from L3A) → TaskCard → Card (structured)
  Card → ExecutionPlan → Step-by-step through AgentTerminals

Example:

  card = Card(
      intent="Add user authentication to login page",
      domain="app/auth",
      phases=[
          Phase(name="investigate", steps=[
              Step("scout",     "structure",  "app/auth/*",     agent="scout"),
          ]),
          Phase(name="implement", steps=[
              Step("write_file",  "app/auth/login.py", params={...}, agent="agent_b"),
              Step("write_file",  "app/auth/login.html", params={...}, agent="agent_a"),
          ], parallel=True),
          Phase(name="review", steps=[
              Step("code_review", "app/auth/login.py", agent="agent_c"),
          ]),
      ],
  )
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class CardMode(Enum):
    EXECUTE = auto()
    ISSUE = auto()
    PARALLEL_ALL = auto()   # all phases run concurrently


class PhaseMode(Enum):
    SEQUENTIAL = auto()   # steps run one by one
    PARALLEL = auto()     # steps run concurrently


@dataclass
class Step:
    """A single atomic unit of work within a Card."""

    action: str = ""
    target: str = ""
    params: dict = field(default_factory=dict)
    agent: str = ""
    depends_on: list[str] = field(default_factory=list)
    verify: dict | None = field(default=None)
    """Verify spec: auto-spawn a scout after this step completes.

    Example:
      Step(action="replace_string", ..., verify={
          "template": "grep",
          "scope": {"pattern": "TODO", "path": "."},
      })
      → ExecutionPlan auto-runs scout before and after,
        diff included in step result.
    """

    def with_agent(self, agent: str) -> Step:
        self.agent = agent
        return self


@dataclass
class Phase:
    """A named group of steps within a Card."""

    name: str = ""
    steps: list[Step] = field(default_factory=list)
    mode: PhaseMode = PhaseMode.SEQUENTIAL
    depends_on: list[str] = field(default_factory=list)  # phase names that must complete first


@dataclass
class Card:
    """Fully structured execution card.

    A Card is the highest-level work item.  It is decomposed into
    Phases → Steps, each routed to an Agent Terminal.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    intent: str = ""
    domain: str = ""
    mode: CardMode = CardMode.EXECUTE
    phases: list[Phase] = field(default_factory=list)
    priority: int = 5
    sender: str = "l3"
    cell_id: str = ""
    created_at: float = field(default_factory=__import__("time").time)

    def all_steps(self) -> list[Step]:
        """Flatten all steps across all phases."""
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


# ── Helpers ──

def make_card(intent: str, domain: str = "",
              steps: list[tuple[str, str, str]] | None = None,
              mode: CardMode = CardMode.EXECUTE) -> Card:
    """Quick card builder: each tuple is (action, target, agent_role).

    Example:
      card = make_card("fix login", "app/auth", [
          ("scout", "app/auth/*", "scout"),
          ("read_file", "app/auth/login.py", "http"),
          ("write_file", "app/auth/login.py", "business"),
      ])
    """
    phases = [Phase(name="work", steps=[
        Step(action=a, target=t, agent=ag) for a, t, ag in (steps or [])
    ])]
    return Card(intent=intent, domain=domain, mode=mode, phases=phases)
