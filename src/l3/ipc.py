"""IPC protocol — 20+ message types, L3 bus, cross-cell routing.

Transport layer: kernel/ipc.LockBus (in-process channel delivery)
Protocol layer:  MessageType, routing matrix, cross-cell routing (this file)

Agent OS spec §2:
  2.1 L3 Message Bus — central routing for all agent communication
  2.2 Message types — 20+ types across 7 categories
  2.3 Communication constraints — allow/deny matrix

MessageType categories:
  L3 → Agent:    task.assign, task.cancel, review.result
  Agent → L3:    task.accept, task.done, task.error, dispute.raise, issue.proposal, scout.request
  Agent ↔ Agent: review.request, review.response, territory.query, agent.message, agent.broadcast
  Scout → Agent: scout.report, scout.progress
  System:        heartbeat, constitution.update, cell.join, cell.leave, cell.restart, scout.timeout
  Direct:        direct.session_start, direct.session_end, direct.message
"""

from __future__ import annotations

import logging
import os
import time
import uuid
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from l1.kernel.ipc import get_lock_bus
from l3._base import BaseService

logger = logging.getLogger(__name__)

from l1.kernel.params.agent import DEFAULT_CELL_ID


class MessageType(Enum):
    # L3 → Agent
    TASK_ASSIGN = "task.assign"
    TASK_CANCEL = "task.cancel"
    REVIEW_RESULT = "review.result"
    CONSTITUTION_UPDATE = "constitution.update"
    CELL_RESTART = "cell.restart"

    # Agent → L3
    TASK_ACCEPT = "task.accept"
    TASK_DONE = "task.done"
    TASK_ERROR = "task.error"
    DISPUTE_RAISE = "dispute.raise"
    ISSUE_PROPOSAL = "issue.proposal"
    SCOUT_REQUEST = "scout.request"

    # Agent ↔ Agent (intra-cell)
    CROSS_REVIEW_REQ = "review.request"
    CROSS_REVIEW_RESP = "review.response"
    TERRITORY_QUERY = "territory.query"
    AGENT_MESSAGE = "agent.message"
    AGENT_BROADCAST = "agent.broadcast"

    # Scout → Agent
    SCOUT_REPORT = "scout.report"
    SCOUT_PROGRESS = "scout.progress"
    SCOUT_TIMEOUT = "scout.timeout"

    # System
    HEARTBEAT = "system.heartbeat"
    HEARTBEAT_TIMEOUT = "system.heartbeat_timeout"
    CELL_JOIN = "system.cell_join"
    CELL_LEAVE = "system.cell_leave"

    # Direct session (human ↔ agent)
    DIRECT_SESSION_START = "direct.session_start"
    DIRECT_SESSION_END = "direct.session_end"
    DIRECT_MESSAGE = "direct.message"


@dataclass
class IPCMessage:
    """Unified IPC message format (§2.2)."""
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str = ""
    receiver: str = ""
    msg_type: MessageType = MessageType.HEARTBEAT
    payload: dict = field(default_factory=dict)
    reply_to: str = ""
    ttl: float = 30.0
    timestamp: float = field(default_factory=time.time)
    signature: str = ""  # AgentProof signature (§6.1)

    def expired(self) -> bool:
        return self.ttl > 0 and (time.time() - self.timestamp) > self.ttl

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


# Communication constraint matrix (§2.3)
COMM_CONSTRAINTS: dict[str, dict[str, bool]] = {
    # path:                    allowed?
    "l3_to_agent":             True,
    "agent_to_l3":             True,
    "agent_to_agent_intra":    True,
    "agent_to_agent_cross":    False,  # requires Ring Omega + constitution check
    "agent_to_scout":          True,  # delegation only
    "scout_to_agent":          True,  # report only
    "scout_to_scout":          False,  # forbidden
    "agent_to_human":          False,  # forbidden, must go through L3
}


class IpcBus(BaseService):
    """L3 Message Bus — central IPC routing (§2.1).

    Transport layer: kernel/ipc.LockBus delivers messages between channels.
    Protocol layer:  MessageType + constraint matrix + cross-cell routing.
    """

    def __init__(self):
        super().__init__("ipc")
        self._lock_bus = get_lock_bus()
        # Each agent gets a LockBus channel for message delivery
        self._channels: dict[str, deque[IPCMessage]] = defaultdict(lambda: deque(maxlen=200))
        self._subscribers: dict[MessageType, list[Callable]] = defaultdict(list)
        self._agents: dict[str, str] = {}  # agent_id → cell_id
        self._lock = threading.RLock()
        self._total_messages = 0
        self._total_dropped = 0

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        self._channels.clear()
        self._subscribers.clear()
        self._agents.clear()
        return {"success": True}

    def _channel_name(self, agent_id: str) -> str:
        return f"ipc:{agent_id}"

    def register_agent(self, agent_id: str, cell_id: str = "") -> None:
        """Register an agent with the bus."""
        if not cell_id:
            cell_id = DEFAULT_CELL_ID
        with self._lock:
            self._agents[agent_id] = cell_id
        logger.debug("agent registered: %s → %s", agent_id, cell_id)

    # ── Send / Receive ──

    def send(self, msg: IPCMessage) -> dict:
        """Send a message. Checks communication constraints."""
        # Check constraints
        constraint_key = self._resolve_constraint(msg.sender, msg.receiver)
        if not COMM_CONSTRAINTS.get(constraint_key, True):
            self._total_dropped += 1
            from .comm_monitor import get_monitor
            get_monitor().record_dropped(channel="ipc")
            return {"success": False, "error": f"communication forbidden: {constraint_key}"}

        with self._lock:
            self._total_messages += 1
            channel = self._get_channel(msg.receiver, msg.msg_type)
            channel.append(msg)
            # Notify subscribers
            for cb in self._subscribers.get(msg.msg_type, []):
                try:
                    cb(msg)
                except Exception as e:
                    logger.warning("ipc handler: %s", e)

        from .comm_monitor import get_monitor
        get_monitor().record_message(channel="ipc", msg_type="send",
                                      direction="out", agent_id=msg.sender,
                                      target=msg.msg_type.name)
        logger.debug("msg sent: %s → %s (%s)", msg.sender, msg.receiver, msg.msg_type.value)
        return {"success": True, "msg_id": msg.msg_id}

    def broadcast(self, msg: IPCMessage) -> dict:
        """Broadcast to all agents."""
        count = 0
        with self._lock:
            for agent_id in self._agents:
                msg.receiver = agent_id
                channel = self._get_channel(agent_id, msg.msg_type)
                channel.append(msg)
                count += 1
                self._total_messages += 1
        return {"success": True, "broadcast_to": count}

    def poll(self, agent_id: str, msg_type: MessageType | None = None) -> list[IPCMessage]:
        """Poll messages for an agent."""
        with self._lock:
            channel = self._channels.get(agent_id)
            if not channel:
                return []
            if msg_type:
                return [m for m in channel if m.msg_type == msg_type and not m.expired()]
            return [m for m in channel if not m.expired()]

    def subscribe(self, msg_type: MessageType, callback: Callable[[IPCMessage], None]) -> None:
        """Subscribe to a message type."""
        with self._lock:
            self._subscribers[msg_type].append(callback)

    def _get_channel(self, key: str, msg_type: MessageType) -> deque:
        return self._channels[key]

    def _get_lock_channel(self, agent_id: str):
        return self._lock_bus.get_channel(self._channel_name(agent_id))

    def _role_prefix(self, agent_id: str) -> str:
        """Extract role prefix from agent ID (e.g. 'agent-http' → 'agent', 'scout-1' → 'scout')."""
        for prefix in ("agent", "scout", "l3", "human", "cell"):
            if agent_id.startswith(prefix):
                return prefix
        return ""

    def _resolve_constraint(self, sender: str, receiver: str) -> str:
        if not sender or not receiver:
            return "unknown"
        sp = self._role_prefix(sender)
        rp = self._role_prefix(receiver)
        if sp == "l3" and rp == "agent":
            return "l3_to_agent"
        if sp == "agent" and rp == "l3":
            return "agent_to_l3"
        if sp == "agent" and rp == "agent":
            if self._same_cell(sender, receiver):
                return "agent_to_agent_intra"
            return "agent_to_agent_cross"
        if sp == "agent" and rp == "scout":
            return "agent_to_scout"
        if sp == "scout" and rp == "agent":
            return "scout_to_agent"
        if sp == "scout" and rp == "scout":
            return "scout_to_scout"
        return "unknown"

    def _same_cell(self, a: str, b: str) -> bool:
        with self._lock:
            return self._agents.get(a) == self._agents.get(b)

    # ── Cross-cell routing (§2.1 Ring Ω) ──

    def route_cross_cell(self, msg: IPCMessage, target_cell: str) -> dict:
        """Route a message to a different cell (Ring Ω)."""
        # Check constitution compatibility
        from_cell = self._agents.get(msg.sender, "unknown")
        if not self._check_constitution_compat(from_cell, target_cell):
            return {"success": False, "error": "constitution incompatible"}
        msg.receiver = f"cell:{target_cell}/{msg.receiver}"
        with self._lock:
            self._total_messages += 1
            channel = self._get_channel(target_cell, msg.msg_type)
            channel.append(msg)
        return {"success": True, "msg_id": msg.msg_id, "route": f"{from_cell} → {target_cell}"}

    def _check_constitution_compat(self, cell_a: str, cell_b: str) -> bool:
        # For MVP: same constitution = compatible
        return True

    # ── Convenience senders ──

    def send_task(self, agent_id: str, task_data: dict, sender: str = "l3") -> dict:
        return self.send(IPCMessage(sender=sender, receiver=agent_id,
                                    msg_type=MessageType.TASK_ASSIGN, payload=task_data))

    def send_review(self, from_agent: str, to_agent: str, task_id: str) -> dict:
        return self.send(IPCMessage(sender=from_agent, receiver=to_agent,
                                    msg_type=MessageType.CROSS_REVIEW_REQ,
                                    payload={"task_id": task_id}))

    def send_scout_report(self, scout_id: str, agent_id: str, findings: list) -> dict:
        return self.send(IPCMessage(sender=scout_id, receiver=agent_id,
                                    msg_type=MessageType.SCOUT_REPORT,
                                    payload={"findings": findings}))

    def send_heartbeat(self, agent_id: str) -> dict:
        return self.send(IPCMessage(sender=agent_id, receiver="l3",
                                    msg_type=MessageType.HEARTBEAT))

    def send_dispute(self, from_agent: str, against: str, reason: str) -> dict:
        return self.send(IPCMessage(sender=from_agent, receiver="l3",
                                    msg_type=MessageType.DISPUTE_RAISE,
                                    payload={"against": against, "reason": reason}))

    def send_direct(self, agent_id: str, message: str, sender: str = "human") -> dict:
        return self.send(IPCMessage(sender=sender, receiver=agent_id,
                                    msg_type=MessageType.DIRECT_MESSAGE,
                                    payload={"text": message}))

    # ── Stats ──

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_messages": self._total_messages,
                "total_dropped": self._total_dropped,
                "agents": len(self._agents),
                "channels": len(self._channels),
                "message_types": {mt.value: len(self._subscribers.get(mt, []))
                                  for mt in MessageType},
            }


_bus: IpcBus | None = None


def get_bus() -> IpcBus:
    global _bus
    if _bus is None:
        _bus = IpcBus()
    return _bus


def reset_bus() -> None:
    global _bus
    if _bus:
        _bus.stop()
    _bus = None