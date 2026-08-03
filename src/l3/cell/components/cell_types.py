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
                     msg_type: Any, payload: Any = None) -> dict:
        """Send a message to another agent in the cell."""
        ...


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


from l1.kernel.params.agent import AGENT_ID_PREFIXES, SCOUT_PREFIX, SUB_PREFIX, DEFAULT_MAX_CONCURRENT_SCOUTS
from l1.kernel.params.system import HASH_TRUNC_MEDIUM, MEMORY_IMPORTANCE_BASE, CELL_CACHE_HOT_TTL, CELL_CACHE_INDEX_TTL


def is_peer(agent_id: str) -> bool:
    """Return True if the agent_id prefix identifies a peer agent."""
    return any(agent_id.startswith(prefix) for prefix in AGENT_ID_PREFIXES)


def is_scout(agent_id: str) -> bool:
    """Return True if the agent_id starts with the scout prefix."""
    return agent_id.startswith(SCOUT_PREFIX)


def is_subagent(agent_id: str) -> bool:
    """Return True if the agent_id starts with the subagent prefix."""
    return agent_id.startswith(SUB_PREFIX)


@dataclass
class AgentInfo:
    role: str = ""
    ring: int = 1
    territory: list[str] = field(default_factory=list)
    max_concurrent_scouts: int = DEFAULT_MAX_CONCURRENT_SCOUTS
    active_scouts: int = 0
    status: AgentStatus = AgentStatus.IDLE
    messages: list[dict] = field(default_factory=list)
    # Per-agent model config (None = use global LLM config)
    model_config: dict | None = None
    # Per-agent prompt key (empty = auto-resolve by role)
    system_prompt_key: str = ""


@dataclass
class CellMessage:
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:HASH_TRUNC_MEDIUM])
    msg_type: MessageType = MessageType.CONSULT
    sender: str = ""
    target: str = ""
    payload: Any = None
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""


# ── Cell L2 Cache types ──


class CacheLocation(Enum):
    """Where a cached entry's full value currently resides."""
    HOT = auto()      # CellCache Hot Ring (fastest)
    KV = auto()       # CellCache KV Cache
    L3 = auto()       # MemoryManager R2/R3 (demoted)
    R4 = auto()       # R4 archive (cold)


@dataclass
class CellCacheEntry:
    """A value entry in the Cell L2 cache.

    Written by a Peer Agent via inject() and immediately visible
    to all other agents in the same Cell via lookup().
    """
    key: str
    value: Any
    summary: str                     # ≤200 chars, low-token preview
    agent_id: str                    # source agent
    entry_type: str                  # "decision" | "observation" | "scout_result" | ...
    cell_id: str
    tokens: int = 0
    importance: float = MEMORY_IMPORTANCE_BASE
    ttl: float = CELL_CACHE_HOT_TTL               # default 5 min
    timestamp: float = field(default_factory=time.time)

    def expired(self, now: float | None = None) -> bool:
        """Return True if the entry's TTL has elapsed relative to the given or current time."""
        if self.ttl <= 0:
            return False
        return (now or time.time()) - self.timestamp > self.ttl


@dataclass
class IndexEntry:
    """Lightweight index chain entry — summary only, no full value.

    Survives even after the full value is demoted to L3/R4.
    Enables low-token-cost pre-check before fetching full data.
    """
    key: str
    summary: str                     # ≤200 chars
    agent_id: str
    entry_type: str
    importance: float = MEMORY_IMPORTANCE_BASE
    timestamp: float = field(default_factory=time.time)
    location: str = "hot"            # "hot" | "kv" | "l3" | "r4"
    ttl: float = CELL_CACHE_INDEX_TTL               # index survives longer (15 min)

    def expired(self, now: float | None = None) -> bool:
        """Return True if the index entry's TTL has elapsed."""
        if self.ttl <= 0:
            return False
        return (now or time.time()) - self.timestamp > self.ttl
