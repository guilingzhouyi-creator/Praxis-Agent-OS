"""Shared types — enums, dataclasses, re-exports."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class AssemblyMode(Enum):
    """AssemblyMode — enum of assembly mode variants."""

    DEFAULT = "default"
    AUTO_APPROVE = "auto_approve"
    CONFERENCE = "conference"


class CardType(Enum):
    """CardType — enum of card type variants."""

    EXECUTION = auto()
    ISSUE = auto()
    DIRECTIVE = auto()
    DIRECT_SESSION = auto()


@dataclass
class SessionRecord:
    """SessionRecord — session record record (session_id, title, created_at, closed_at, turn_count)."""

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
    """TaskCard — task card record (id, intent, card_type, domain, cell)."""

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
    """A subagent task tracked by the L3A session task table."""

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
        """Return True when the task reached a terminal status."""
        return self.status in ("done", "error", "timeout")


@dataclass
class L3ATaskGroup:
    """Group of subagent task ids collected at once."""

    group_id: str = ""
    task_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
