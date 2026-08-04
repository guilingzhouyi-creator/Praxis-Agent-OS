"""Terminal data types — extracted from agent_terminal.py for modularity."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto

from l1.kernel.params.system import HASH_TRUNC_MEDIUM


class TerminalStatus(Enum):
    """TerminalStatus — enum of terminal status variants."""
    BOOTING = auto(); IDLE = auto(); PROCESSING = auto()
    WAITING_SCOUT = auto(); WAITING_CONSENSUS = auto()
    REVIEWING = auto(); BLOCKED = auto(); CRASHED = auto(); STOPPED = auto()


class CardMode(Enum):
    """CardMode — enum of card mode variants."""
    EXECUTE = auto()
    ISSUE = auto()


@dataclass
class TerminalCard:
    """TerminalCard — terminal card record (card_id, mode, action, target, params)."""
    card_id: str = field(default_factory=lambda: uuid.uuid4().hex[:HASH_TRUNC_MEDIUM])
    mode: CardMode = CardMode.EXECUTE
    action: str = ""
    target: str = ""
    params: dict = field(default_factory=dict)
    sender: str = ""
    reply_to: str = ""
    timestamp: float = field(default_factory=time.time)
    batch: list[dict] = field(default_factory=list)  # multiple tool_use for Agent internal parallel


@dataclass
class CardResult:
    """CardResult — card result record (card_id, action, success, output, error)."""
    card_id: str
    action: str
    success: bool
    output: str = ""
    error: str = ""
    findings: list[dict] = field(default_factory=list)
    elapsed: float = 0.0
    phase: list[str] = field(default_factory=list)
