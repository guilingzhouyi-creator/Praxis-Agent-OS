"""L3B communication bus — dedicated bus for inter-composite communication.

Each L3B+HTN-B composite communicates with its neighbors via this bus:
  L3B[1↔2] ←→ L3B[2↔3] ←→ L3B[3↔4] ←→ ...

Topology:
  Chain + hop-by-hop forwarding (composites cannot communicate across levels)
  Message types:
    - CARD_FORWARD: forward card fragments
    - RESULT_BACK:  send execution results backward
    - STATUS_CHECK: status query
    - BACKPRESSURE: backpressure signal (notify upstream to slow down when downstream is busy)

Bus implementation:
  Each composite registers one mailbox queue on the bus.
  Messages are routed to the target by composite_id.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.params.system import L3B_MAILBOX_MAXLEN, SCOUT_POOL_IDLE_TIMEOUT

logger = logging.getLogger(__name__)


class L3BMessageType(Enum):
    """L3BMessageType — enum of CARD_FORWARD, RESULT_BACK, STATUS_CHECK, BACKPRESSURE...."""
    CARD_FORWARD = auto()        # forward card fragments
    RESULT_BACK = auto()         # send execution results backward
    STATUS_CHECK = auto()        # status query
    BACKPRESSURE = auto()        # backpressure signal
    HEARTBEAT = auto()           # heartbeat


@dataclass
class L3BMessage:
    """L3BMessage — l3 b message record (msg_id, msg_type, sender, target, payload)."""
    msg_id: str = ""
    msg_type: L3BMessageType = L3BMessageType.CARD_FORWARD
    sender: str = ""             # composite_id
    target: str = ""             # composite_id
    payload: Any = None
    timestamp: float = field(default_factory=time.time)
    ttl: float = SCOUT_POOL_IDLE_TIMEOUT            # message timeout auto-discard


class L3BBus:
    """L3B communication bus — message routing between composites.

    Each composite registers one mailbox queue.
    Message routing is based on composite_id (chain topology, only adjacent communication allowed).
    """

    def __init__(self):
        self._mailboxes: dict[str, deque[L3BMessage]] = {}
        self._lock = threading.Lock()
        self._stats: dict = {
            "sent": 0,
            "received": 0,
            "expired": 0,
            "backpressure": 0,
        }

    def register(self, composite_id: str) -> dict:
        """Register a composite on the bus.

        Each composite has its own mailbox queue (ring buffer, max=200).
        """
        with self._lock:
            if composite_id not in self._mailboxes:
                self._mailboxes[composite_id] = deque(maxlen=L3B_MAILBOX_MAXLEN)
                logger.info("L3BBus: registered %s", composite_id)
            return {"success": True, "composite_id": composite_id}

    def unregister(self, composite_id: str) -> dict:
        """Unregister a composite from the bus. Returns a result dict."""
        with self._lock:
            self._mailboxes.pop(composite_id, None)
            logger.info("L3BBus: unregistered %s", composite_id)
            return {"success": True}

    def send(self, sender: str, target: str, msg_type: L3BMessageType,
             payload: Any = None) -> dict:
        """Send a message to a target composite.

        Chain rule: only adjacent composites may communicate.
        Messages for non-adjacent composites are rejected.
        """
        # resolve adjacency
        sender_parts = sender.split("-")
        target_parts = target.split("-")
        # composite_id format: "l3b-{cell_a}-{cell_b}"
        # Only composites sharing a Cell ID are adjacent
        sender_cells = {sender_parts[1], sender_parts[2]} if len(sender_parts) >= 3 else set()
        target_cells = {target_parts[1], target_parts[2]} if len(target_parts) >= 3 else set()
        is_adjacent = bool(sender_cells & target_cells) if sender_cells and target_cells else False

        with self._lock:
            mailbox = self._mailboxes.get(target)
            if mailbox is None:
                return {"success": False, "error": f"target {target} not registered"}

            if not is_adjacent:
                # Non-adjacent composites: forward via chain (relay through intermediate composite)
                # First find an intermediate composite
                mid = self._find_relay(sender, target)
                if mid:
                    relay_msg = L3BMessage(
                        msg_id=f"relay-{time.time_ns()}",
                        msg_type=msg_type,
                        sender=sender,
                        target=target,
                        payload=payload,
                    )
                    mailbox = self._mailboxes.get(mid)
                    if mailbox is None:
                        return {"success": False, "error": f"relay {mid} not found"}
                    mailbox.append(relay_msg)
                    self._stats["sent"] += 1
                    return {"success": True, "relayed_via": mid}

                return {"success": False, "error": "no route to target"}

            msg = L3BMessage(
                msg_id=f"msg-{time.time_ns()}",
                msg_type=msg_type,
                sender=sender,
                target=target,
                payload=payload,
            )
            mailbox.append(msg)
            self._stats["sent"] += 1
            self._mirror_send(sender, target, msg_type, payload)
            return {"success": True}

    def _mirror_send(self, sender: str, target: str, msg_type: L3BMessageType,
                     payload: dict | None = None) -> None:
        """Mirror an L3B send to the MonitorBus observability stream."""
        try:
            from l3.bus.monitor_bus import MonitorEvent, get_bus
            get_bus().emit(MonitorEvent(
                type="l3b.message", source="l3b_bus", severity="info",
                message=f"L3B {sender} -> {target} ({msg_type.value})",
                data={"sender": sender, "target": target,
                      "msg_type": msg_type.value, "payload": payload or {}},
            ))
        except Exception as e:
            logger.debug("l3b_bus: monitor emit failed: %s", e)

    def read(self, composite_id: str, limit: int = 10,
             clear: bool = True) -> list[dict]:
        """Read messages from a target composite's mailbox.

        Returns a list of messages, optionally leaving them in place (non-destructive read).
        """
        now = time.time()
        with self._lock:
            mailbox = self._mailboxes.get(composite_id)
            if mailbox is None:
                return []

            messages = []

            for msg in mailbox:
                # expiry check
                if msg.ttl > 0 and now - msg.timestamp > msg.ttl:
                    self._stats["expired"] += 1
                    continue
                messages.append({
                    "msg_id": msg.msg_id,
                    "msg_type": msg.msg_type.name,
                    "sender": msg.sender,
                    "target": msg.target,
                    "payload": msg.payload,
                    "timestamp": msg.timestamp,
                })
                if len(messages) >= limit:
                    break

            if clear:
                # Destructive read: drop consumed messages, keep unread ones.
                consumed_ids = {m["msg_id"] for m in messages}
                kept: deque[L3BMessage] = deque(maxlen=mailbox.maxlen)
                for msg in mailbox:
                    if msg.msg_id not in consumed_ids:
                        kept.append(msg)
                self._mailboxes[composite_id] = kept
            # clear=False → non-destructive: mailbox left untouched

            self._stats["received"] += len(messages)
            return messages

    def send_backpressure(self, sender: str, target: str,
                          reason: str = "") -> dict:
        """Send a backpressure signal: downstream tells upstream to reduce sending rate."""
        self._stats["backpressure"] += 1
        return self.send(sender, target, L3BMessageType.BACKPRESSURE, {
            "reason": reason,
            "timestamp": time.time(),
        })

    def _find_relay(self, sender: str, target: str) -> str | None:
        """Find a forwarding path in the chain topology.

        Composite chain: l3b-cell1-cell2, l3b-cell2-cell3, l3b-cell3-cell4
        If sender=l3b-cell1-cell2, target=l3b-cell3-cell4
        then relay = l3b-cell2-cell3
        """
        sender_cells = set(sender.split("-")[1:3]) if len(sender.split("-")) >= 3 else set()
        target_cells = set(target.split("-")[1:3]) if len(target.split("-")) >= 3 else set()

        for cid in list(self._mailboxes.keys()):
            cid_cells = set(cid.split("-")[1:3]) if len(cid.split("-")) >= 3 else set()
            # Find an intermediate composite that shares a Cell with both sender and target
            if cid != sender and cid != target:
                if cid_cells & sender_cells and cid_cells & target_cells:
                    return cid
        return None

    def stats(self) -> dict:
        """Bus statistics."""
        with self._lock:
            return {
                **self._stats,
                "registered_composites": len(self._mailboxes),
                "mailboxes": {
                    cid: len(mbox)
                    for cid, mbox in self._mailboxes.items()
                },
            }


# ── Global Singleton ──

_bus: L3BBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> L3BBus:
    """Get the L3B message bus singleton."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = L3BBus()
    return _bus


def reset_bus() -> None:
    """Reset the L3B message bus singleton. Returns None."""
    global _bus
    _bus = None
