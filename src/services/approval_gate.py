"""Human approval gate — persisted, blocks tool execution until human confirms."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from kernel.params import APPROVAL_GATE_PATH, APPROVAL_GATE_AUTO_SAVE, APPROVAL_GATE_WAIT_TIMEOUT
from services._persistable import PersistableMixin

logger = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    id: str = field(default_factory=lambda: f"apr-{uuid.uuid4().hex[:8]}")
    tool_name: str = ""
    agent_id: str = ""
    args: dict = field(default_factory=dict)
    reason: str = ""
    status: str = PENDING
    created_at: float = field(default_factory=time.time)
    responded_at: float = 0.0
    response: str = ""
    _event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def approve(self, response: str = "") -> None:
        self.status = APPROVED
        self.responded_at = time.time()
        self.response = response
        self._event.set()

    def reject(self, response: str = "") -> None:
        self.status = REJECTED
        self.responded_at = time.time()
        self.response = response
        self._event.set()

    def wait(self, timeout: float = APPROVAL_GATE_WAIT_TIMEOUT) -> str:
        self._event.wait(timeout=timeout)
        if self.status == PENDING:
            self.status = TIMEOUT
        return self.status


class ApprovalGate(PersistableMixin):
    """Manages pending human approval requests — persisted across restarts."""

    persistence_kind = "approval_gate"

    def __init__(self, persist_path: str = ""):
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = threading.RLock()
        self._init_persistence(persist_path or APPROVAL_GATE_PATH, APPROVAL_GATE_AUTO_SAVE)
        self._restore()
        # Expire any stale pending requests from before restart
        now = time.time()
        expired = 0
        with self._lock:
            for ar in list(self._requests.values()):
                if ar.status == PENDING and (now - ar.created_at) > 3600:
                    ar.status = TIMEOUT
                    expired += 1
            if expired:
                self._persist()
        if APPROVAL_GATE_AUTO_SAVE > 0:
            self._start_auto_save()

    def _serialize(self) -> dict:
        return {
            "requests": {rid: {
                "id": r.id, "tool_name": r.tool_name, "agent_id": r.agent_id,
                "args": {k: str(v)[:200] for k, v in r.args.items()},
                "reason": r.reason, "status": r.status,
                "created_at": r.created_at, "responded_at": r.responded_at,
                "response": r.response,
            } for rid, r in self._requests.items()},
        }

    def _deserialize(self, data: dict) -> bool:
        self._requests.clear()
        for rid, d in data.get("requests", {}).items():
            ar = ApprovalRequest(
                id=d["id"], tool_name=d.get("tool_name", ""),
                agent_id=d.get("agent_id", ""),
                args=d.get("args", {}), reason=d.get("reason", ""),
                status=d.get("status", PENDING),
                created_at=d.get("created_at", 0.0),
                responded_at=d.get("responded_at", 0.0),
                response=d.get("response", ""),
            )
            self._requests[rid] = ar
        return True

    def request(self, tool_name: str, agent_id: str, args: dict,
                reason: str = "") -> ApprovalRequest:
        ar = ApprovalRequest(tool_name=tool_name, agent_id=agent_id,
                             args=args, reason=reason)
        with self._lock:
            self._requests[ar.id] = ar
            self._persist()
        logger.info("approval required: %s calls %s by %s", ar.id, tool_name, agent_id)
        return ar

    def respond(self, req_id: str, approved: bool, response: str = "") -> dict:
        with self._lock:
            ar = self._requests.get(req_id)
            if not ar:
                return {"success": False, "error": f"unknown request: {req_id}"}
            if ar.status != PENDING:
                return {"success": False, "error": f"request already {ar.status}"}
            if approved:
                ar.approve(response)
            else:
                ar.reject(response)
            self._persist()
        return {"success": True, "status": ar.status}

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [
                {"id": r.id, "tool_name": r.tool_name, "agent_id": r.agent_id,
                 "reason": r.reason, "created_at": r.created_at,
                 "args": {k: str(v)[:100] for k, v in r.args.items()}}
                for r in self._requests.values() if r.status == PENDING
            ]

    def stats(self) -> dict:
        with self._lock:
            total = len(self._requests)
            pending = sum(1 for r in self._requests.values() if r.status == PENDING)
            return {"total": total, "pending": pending}


_gate: ApprovalGate | None = None


def get_gate() -> ApprovalGate:
    global _gate
    if _gate is None:
        _gate = ApprovalGate()
    return _gate


def reset_gate() -> None:
    global _gate
    _gate = None
