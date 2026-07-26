"""Cell data types — shared data structures for Cell module.

Architecture:
  L3A (an Agent) interprets human natural language → produces a Card.
  The Card defines what work is needed and which agent role it targets.
  The Cell holds N peer agents — their identities are NOT hardcoded.
  Agent roles are determined by the Card at dispatch time.

  A Cell also has:
    - Scout pool: Ring 1 only, investigation, pool-managed
    - SubAgent:   Ring 1 only, synchronous quick-check, spawned per-call
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CellProtocol(Protocol):
    """Protocol that Cell must satisfy — avoids circular imports.

    Modules like ConventionProtocol depend on Cell for messaging.
    This protocol defines the minimum required interface.
    """
    cell_id: str
    territory: list[str]

    def send_message(self, sender: str, target: str,
                     msg_type: Any, payload: Any = None) -> dict: ...


class AgentStatus(Enum):
    IDLE = auto()
    BUSY = auto()
    WAITING = auto()
    BLOCKED = auto()


class MessageType(Enum):
    TASK_HANDOFF = auto()
    SCOUT_RESULT = auto()
    CONSULT = auto()
    VOTE_REQUEST = auto()
    VOTE_RESPONSE = auto()
    ESCALATE = auto()
    CROSS_REVIEW_REQ = auto()
    CROSS_REVIEW_RESP = auto()
    SUBAGENT_RESULT = auto()
    # Convention / Assembly protocol
    CONVENE = auto()          # Convene assembly (L3A → All Agents)
    CROSS_EXAMINE = auto()    # Cross-examine specific Agent (Agent → Agent)
    REBUT = auto()            # Rebuttal (Agent → All)
    PROPOSE_ISSUE = auto()    # Propose new issue (Agent → Table)
    CONVENE_CLOSE = auto()    # Close assembly (Convention → All)


from kernel.params.agent import AGENT_ID_PREFIXES, SCOUT_PREFIX, SUB_PREFIX


def is_peer(agent_id: str) -> bool:
    return any(agent_id.startswith(prefix) for prefix in AGENT_ID_PREFIXES)


def is_scout(agent_id: str) -> bool:
    return agent_id.startswith(SCOUT_PREFIX)


def is_subagent(agent_id: str) -> bool:
    return agent_id.startswith(SUB_PREFIX)


@dataclass
class AgentInfo:
    role: str = ""
    ring: int = 1
    territory: list[str] = field(default_factory=list)
    max_concurrent_scouts: int = 3
    active_scouts: int = 0
    status: AgentStatus = AgentStatus.IDLE
    messages: list[dict] = field(default_factory=list)
    # Per-agent model config (None = use global LLM config)
    model_config: dict | None = None
    # Per-agent prompt key (empty = auto-resolve by role)
    system_prompt_key: str = ""


@dataclass
class CellMessage:
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    msg_type: MessageType = MessageType.CONSULT
    sender: str = ""
    target: str = ""
    payload: Any = None
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""
