"""Plan step data types — extracted from execution_plan.py."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class StepState(Enum):
    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class PlanStep:
    """A single step in the execution plan — one action for one agent."""
    step_id: str = ""
    action: str = ""
    target: str = ""
    params: dict = field(default_factory=dict)
    agent: str = ""
    phase: str = ""
    depends_on: list[str] = field(default_factory=list)
    state: StepState = StepState.PENDING
    result: dict = field(default_factory=dict)
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def elapsed(self) -> float:
        if self.completed_at:
            return self.completed_at - self.started_at
        return time.time() - self.started_at if self.started_at else 0.0
