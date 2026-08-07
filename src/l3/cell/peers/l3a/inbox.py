"""PromptInbox — durable admission/promotion for pending prompts.

Mirrors OpenCode V2's concept:
  - admit(text, mode) → Admission (pending)
  - promote() → Admission (moved to SessionHistory)
  - "steer" mode: promote on next Safe Provider-Turn Boundary
  - "queue" mode: promote when Session would otherwise be idle
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from l3.error_bus import capture

from . import params as _p

logger = logging.getLogger(__name__)


@dataclass
class Admission:
    """Admission — admission record (id, session_id, text, mode, status)."""
    id: str
    session_id: str
    text: str
    mode: str
    status: str
    created_at: float = field(default_factory=time.time)
    promoted_at: float | None = None


class PromptInbox:
    """PromptInbox — prompt inbox."""
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._entries: list[Admission] = []
        self._lock = threading.Lock()
        self._persisted_ids: set[str] = set()

    def admit(self, text: str, mode: str = "steer") -> Admission:
        """Admit a prompt entry into the inbox and return the created Admission."""
        a = Admission(
            id=uuid.uuid4().hex[:_p.SID_LENGTH],
            session_id=self._session_id,
            text=text,
            mode=mode,
            status="pending",
        )
        with self._lock:
            self._entries.append(a)
        self._persist()
        return a

    def promote(self) -> Admission | None:
        """Promote the next pending admission.

        Ordering semantics (per l3a-assembly.md):
          - ``steer`` admissions promote first (drain ASAP);
          - ``queue`` admissions only promote when no steer is pending
            (i.e. when the session would otherwise be idle).
        """
        with self._lock:
            for a in self._entries:
                if a.status == "pending" and a.mode == "steer":
                    a.status = "promoted"
                    a.promoted_at = time.time()
                    self._persist()
                    return a
            for a in self._entries:
                if a.status == "pending":
                    a.status = "promoted"
                    a.promoted_at = time.time()
                    self._persist()
                    return a
        return None

    def peek(self) -> Admission | None:
        """Return the first pending admission without promoting it, or None."""
        with self._lock:
            for a in self._entries:
                if a.status == "pending":
                    return a
        return None

    def pending(self) -> list[Admission]:
        """Return all admissions that are still pending."""
        with self._lock:
            return [a for a in self._entries if a.status == "pending"]

    def pending_count(self) -> int:
        """O(1) count of pending admissions — avoids list allocation."""
        with self._lock:
            return sum(1 for a in self._entries if a.status == "pending")

    def cancel(self, admission_id: str) -> bool:
        """Cancel a pending admission by id, returning True when cancelled."""
        with self._lock:
            for a in self._entries:
                if a.id == admission_id and a.status == "pending":
                    a.status = "cancelled"
                    self._persist()
                    return True
        return False

    def reload(self) -> None:
        """Reload persisted inbox entries for this session from central memory."""
        try:
            from l3.memory.central_memory import get_l3a_memory as _gm
            entries = _gm().recall(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_inbox",
                tag=f"session:{self._session_id}",
                rings=[2],
                limit=_p.INBOX_RELOAD_LIMIT,
            )
        except Exception:
            capture("l3a inbox: reload failed", error_code="E_L3A_INBOX", component="l3a", context={"session_id": self._session_id})
            logger.warning("l3a inbox: reload failed, starting fresh")
            return
        with self._lock:
            self._entries.clear()
            for e in entries:
                try:
                    data = json.loads(e.content)
                    self._entries.append(Admission(**data))
                except Exception:
                    capture("l3a inbox: entry parse failed", error_code="E_L3A_INBOX", component="l3a")
                    continue

    def _persist(self) -> None:
        try:
            from l3.memory.central_memory import get_l3a_memory as _gm
            for a in self._entries:
                if a.status != "pending" or a.id in self._persisted_ids:
                    continue
                _gm().remember(
                    agent_id=_p.AGENT_ID,
                    entry_type="l3a_inbox",
                    content=json.dumps({
                        "id": a.id, "session_id": a.session_id,
                        "text": a.text, "mode": a.mode, "status": a.status,
                        "created_at": a.created_at,
                    }, default=str),
                    tags=["l3a", "inbox", f"session:{self._session_id}"],
                    importance=_p.INBOX_IMPORTANCE,
                    ring=2,
                )
                self._persisted_ids.add(a.id)
        except Exception:
            capture("l3a inbox: persist failed", error_code="E_L3A_INBOX", component="l3a", context={"session_id": self._session_id})
            logger.warning("l3a inbox: persist failed")
