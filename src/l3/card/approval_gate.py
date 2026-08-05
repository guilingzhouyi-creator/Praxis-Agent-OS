"""Human approval gate — persisted, blocks tool execution until human confirms."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from l1.kernel.discovery import get_config as _get_config
from l1.kernel.params.system import HASH_TRUNC_SHORT, LOG_TRUNC_100, LOG_TRUNC_200
from l1.kernel.paths import get_paths as _gp
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
TIMEOUT = "timeout"

# Resolve persistence defaults from config with params fallback
from l1.kernel.params.system import APPROVAL_GATE_AUTO_SAVE as _DEFAULT_AUTO_SAVE
from l1.kernel.params.system import APPROVAL_GATE_WAIT_TIMEOUT as _DEFAULT_WAIT_TIMEOUT

_AUTO_SAVE: float = _DEFAULT_AUTO_SAVE
_WAIT_TIMEOUT: float = _DEFAULT_WAIT_TIMEOUT
_cfg = _get_config("persistence")
if _cfg:
    _AUTO_SAVE = float(_cfg.get("approval_gate", _AUTO_SAVE))
    _WAIT_TIMEOUT = float(_cfg.get("approval_wait_timeout", _WAIT_TIMEOUT))


@dataclass
class ApprovalRequest:
    """ApprovalRequest — approval request record (id, tool_name, agent_id, args, reason)."""
    id: str = field(default_factory=lambda: f"apr-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}")
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
        """Mark this request approved and wake any waiters."""
        self.status = APPROVED
        self.responded_at = time.time()
        self.response = response
        self._event.set()

    def reject(self, response: str = "") -> None:
        """Mark this request rejected and wake any waiters."""
        self.status = REJECTED
        self.responded_at = time.time()
        self.response = response
        self._event.set()

    def wait(self, timeout: float | None = None) -> str:
        """Block until the request is answered or timeout, returning final status."""
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
        self._init_persistence(persist_path or _gp().approval_gate, _AUTO_SAVE)
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
        if _AUTO_SAVE > 0:
            self._start_auto_save()

    def _serialize(self) -> dict:
        return {
            "requests": {rid: {
                "id": r.id, "tool_name": r.tool_name, "agent_id": r.agent_id,
                "args": {k: str(v)[:LOG_TRUNC_200] for k, v in r.args.items()},
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
        """Create and persist a new approval request, returning it."""
        ar = ApprovalRequest(tool_name=tool_name, agent_id=agent_id,
                             args=args, reason=reason)
        with self._lock:
            self._requests[ar.id] = ar
            self._persist()
        logger.info("approval required: %s calls %s by %s", ar.id, tool_name, agent_id)
        # Frontend notification chain: approval needed
        try:
            from l1.kernel import emit_signal

            emit_signal("APPROVAL_REQUIRED", sender="approval_gate",
                        target="cell", data={"req_id": ar.id, "tool_name": tool_name,
                                             "agent_id": agent_id, "reason": reason})
        except Exception:
            logger.debug("approval_gate: APPROVAL_REQUIRED emit failed")
        return ar

    def respond(self, req_id: str, approved: bool, response: str = "") -> dict:
        """Approve or reject a pending request, returning a result dict."""
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
        # Frontend notification chain: approval response committed
        try:
            from l1.kernel import emit_signal

            emit_signal("APPROVAL_RESPONDED", sender="approval_gate",
                        target="cell", data={"req_id": req_id, "approved": approved,
                                             "response": response,
                                             "status": ar.status})
        except Exception:
            logger.debug("approval_gate: APPROVAL_RESPONDED emit failed")
        return {"success": True, "status": ar.status}

    def list_pending(self) -> list[dict]:
        """Return a list of summary dicts for all pending requests."""
        with self._lock:
            return [
                {"id": r.id, "tool_name": r.tool_name, "agent_id": r.agent_id,
                 "reason": r.reason, "created_at": r.created_at,
                 "args": {k: str(v)[:LOG_TRUNC_100] for k, v in r.args.items()}}
                for r in self._requests.values() if r.status == PENDING
            ]

    def stats(self) -> dict:
        """Return a dict with total and pending request counts."""
        with self._lock:
            total = len(self._requests)
            pending = sum(1 for r in self._requests.values() if r.status == PENDING)
            return {"total": total, "pending": pending}


_gate: ApprovalGate | None = None


def get_gate() -> ApprovalGate:
    """Return the shared global ApprovalGate, creating it if needed."""
    global _gate
    if _gate is None:
        _gate = ApprovalGate()
    return _gate


def reset_gate() -> None:
    """Reset the shared global ApprovalGate to None."""
    global _gate
    _gate = None
