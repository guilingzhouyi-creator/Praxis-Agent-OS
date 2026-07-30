"""Shared types — enums, dataclasses, re-exports."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class AssemblyMode(Enum):
    DEFAULT = "default"
    AUTO_APPROVE = "auto_approve"
    CONFERENCE = "conference"


class CardType(Enum):
    EXECUTION = auto()
    ISSUE = auto()
    DIRECTIVE = auto()
    DIRECT_SESSION = auto()


@dataclass
class SessionRecord:
    session_id: str = ""
    title: str = ""
    created_at: str = ""
    closed_at: str = ""
    turn_count: int = 0
    card_count: int = 0
    model_spec: str = ""
    tags: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class TaskCard:
    id: str = ""
    intent: str = ""
    card_type: CardType = CardType.EXECUTION
    domain: str = ""
    cell: str = ""
    priority: int = 5
    tools_hint: list[str] = field(default_factory=list)
    agent_id: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class L3ATask:
    task_id: str = ""
    spec: str = ""
    task: str = ""
    group: str = ""
    expect: dict | None = None
    status: str = "pending"
    result: dict | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    future: Any | None = None

    def is_done(self) -> bool:
        return self.status in ("done", "error", "timeout")


@dataclass
class L3ATaskGroup:
    group_id: str = ""
    task_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
