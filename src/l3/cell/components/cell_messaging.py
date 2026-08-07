"""Cell messaging mixin — inter-agent messaging, direct messages, liveness.

Extracted from cell/__init__.py to reduce the 1091-line Cell class."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from l1.kernel import Signal, SignalType
from l1.kernel.params.agent import CELL_MAILBOX_MAX_PER_AGENT, CELL_MAILBOX_TTL

if TYPE_CHECKING:
    from l3.cell.components.cell_types import AgentInfo, CellMessage

logger = logging.getLogger(__name__)


class CellMessagingMixin:
    """Mixin providing Cell messaging methods — send, read, liveness, direct."""

    # ── Attributes injected by the concrete Cell (see cell/__init__.py) ──
    cell_id: str
    territory: list[str]
    _lock: threading.RLock
    _agents: dict[str, AgentInfo]
    _mailbox: dict[str, list[CellMessage]]
    _bus: Any
    _pmu: Any

    # ── Agent-to-Agent Messaging ──

    def send_message(self, sender: str, target: str,
                     msg_type: Any, payload: Any = None) -> dict:
        """Send a message to an agent within this Cell."""
        from l3.cell.components.cell_types import CellMessage, MessageType
        CONVENTION_TYPES = frozenset({
            MessageType.CONVENE, MessageType.CROSS_EXAMINE,
            MessageType.REBUT, MessageType.PROPOSE_ISSUE,
            MessageType.CONVENE_CLOSE,
        })
        with self._lock:
            if target not in self._agents:
                return {"success": False, "error": f"unknown target: {target}"}
            if sender not in self._agents:
                return {"success": False, "error": f"unknown sender: {sender}"}
            now = time.time()
            inbox = self._mailbox.setdefault(target, [])
            inbox[:] = [m for m in inbox if now - m.timestamp < CELL_MAILBOX_TTL]
            if len(inbox) >= CELL_MAILBOX_MAX_PER_AGENT:
                inbox.pop(0)
            msg = CellMessage(msg_type=msg_type, sender=sender, target=target, payload=payload)
            inbox.append(msg)
            self._bus.emit(Signal(type=SignalType.TASK_ASSIGN, sender=sender,
                                  target=target, data={"cell": self.cell_id, "msg_type": msg_type.name}))
        self._pmu.increment("bus.messages_sent")
        from l3.bus.comm_monitor import get_monitor
        get_monitor().record_message(channel="cell_mailbox", msg_type="send",
                                      direction="out", agent_id=sender, target=target)
        if msg_type in CONVENTION_TYPES:
            try:
                from l3.agent_terminal import CardMode as TermCardMode
                from l3.agent_terminal import TerminalCard, get_terminal
                term = get_terminal(target)
                from l1.kernel.params.agent import AGENT_STATUS_CRASHED
                if term.status.name not in (AGENT_STATUS_CRASHED,):
                    tcard = TerminalCard(
                        mode=TermCardMode.EXECUTE,
                        action="convention",
                        target=payload.get("card_id", "conv-unknown"),
                        params={"msg_type": msg_type.name, "payload": payload, "sender": sender},
                        sender="cell",
                    )
                    term.dispatch(tcard)
            except Exception as e:
                logger.warning("cell dispatch convention card to %s failed: %s", target, e)
        return {"success": True, "msg_id": msg.msg_id}

    def read_messages(self, agent_id: str, clear: bool = True) -> list[dict]:
        """Read pending messages for an agent."""
        with self._lock:
            msgs = self._mailbox.get(agent_id, [])
            if clear:
                self._mailbox[agent_id] = []
            return [
                {"msg_id": m.msg_id, "type": m.msg_type.name,
                 "sender": m.sender, "payload": m.payload, "timestamp": m.timestamp}
                for m in msgs
            ]

    def agent_reachable(self, agent_id: str) -> dict:
        """Check if a specific agent can accept a direct message."""
        from l3.agent_terminal import get_terminals
        term = get_terminals().get(agent_id)
        if not term:
            return {"reachable": False, "reason": "no_terminal", "agent_id": agent_id}
        return term.session_reachable()

    def send_direct_message(self, agent_id: str, text: str) -> dict:
        """Send a direct message to an agent via its stdin queue."""
        from l3.agent_terminal import get_terminals
        term = get_terminals().get(agent_id)
        if not term:
            return {"success": False, "error": f"unknown agent: {agent_id}"}
        r = term.session_reachable()
        if not r.get("reachable"):
            return {"success": False, "error": f"unreachable: {r.get('reason')}"}
        return term.send_direct_message(text)

    def liveness(self) -> dict:
        """Check Cell and all agent terminals liveness.

        Used by Shell (L2) Direct Mode to verify target reachability.
        Returns aggregate status: healthy / degraded / unreachable.
        """
        from l3.agent_terminal import get_terminals
        terms = get_terminals()
        agent_results = {}
        healthy_count = 0
        total_count = 0
        with self._lock:
            agent_ids = list(self._agents.keys())
        for aid in agent_ids:
            total_count += 1
            term = terms.get(aid)
            if term is None:
                agent_results[aid] = {"status": "no_terminal", "alive": False}
                continue
            from l1.kernel.params.agent import (
                AGENT_STATUS_BOOTING,
                AGENT_STATUS_IDLE,
                AGENT_STATUS_PROCESSING,
                AGENT_STATUS_WAITING_SCOUT,
            )
            if term.status.name in (AGENT_STATUS_IDLE, AGENT_STATUS_PROCESSING, AGENT_STATUS_WAITING_SCOUT):
                agent_results[aid] = {"status": term.status.name.lower(), "alive": True}
                healthy_count += 1
            elif term.status.name in (AGENT_STATUS_BOOTING,):
                agent_results[aid] = {"status": "booting", "alive": True}
                healthy_count += 1
            else:
                agent_results[aid] = {"status": term.status.name, "alive": False}

        if healthy_count == total_count:
            overall = "healthy"
        elif healthy_count > 0:
            overall = "degraded"
        else:
            overall = "unreachable"

        return {
            "cell_id": self.cell_id,
            "overall": overall,
            "agents": agent_results,
            "healthy": healthy_count,
            "total": total_count,
            "territory": self.territory,
        }

    def agent_status(self, agent_id: str) -> dict:
        """Return the current status of a specific agent."""
        from l3.cell.components.cell_agent import agent_status as _agent_status
        return _agent_status(self, agent_id)

    def close_direct_session(self, agent_id: str) -> dict:
        """Close a direct session for the given agent."""
        from l3.agent_terminal import get_terminals
        term = get_terminals().get(agent_id)
        if not term:
            return {"success": False, "error": f"unknown agent: {agent_id}"}
        r = term.session_reachable()
        if not r.get("reachable"):
            return {"success": True, "note": "session already closed"}
        # Direct session is stateless per message — no persistent session to close.
        # Future: send a DIRECT_SESSION_END IPC message for stateful tracking.
        return {"success": True, "agent_id": agent_id}
