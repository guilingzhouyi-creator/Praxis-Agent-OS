"""Scheduler data types — shared across scheduling sub-modules."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.params.system import SCHEDULER_BACKGROUND_PRIORITY, DEFAULT_QUANTUM, MAX_PREEMPT


class TaskPriority(Enum):
    CRITICAL = 1
    HIGH = 3
    NORMAL = 5
    LOW = 8
    BACKGROUND = SCHEDULER_BACKGROUND_PRIORITY


@dataclass
class Task:
    id: str
    agent_id: str
    command: str
    args: dict = field(default_factory=dict)
    priority: int = TaskPriority.NORMAL.value
    dependencies: list[str] = field(default_factory=list)
    estimated_duration: float = 0.0
    submitted_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    result: Any = None
    error: str = ""


@dataclass
class AgentInfo:
    id: str
    territory: list[str]
    reputation: float = 0.85
    load: float = 0.0
    active_tasks: int = 0
    last_seen: float = field(default_factory=time.time)
    affinity_tags: list[str] = field(default_factory=list)


@dataclass
class TimeSlice:
    agent_id: str
    quantum: float = DEFAULT_QUANTUM
    used: float = 0.0
    deadline: float = 0.0
    preempted: bool = False
    started_at: float = 0.0
    priority: int = 5
    wait_since: float = field(default_factory=time.time)
