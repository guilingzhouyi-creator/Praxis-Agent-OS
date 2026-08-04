"""Card Gate — card size classification, approval routing, dispatch gate.

Card size determines approval workflow:
  small:     auto-approve, direct dispatch to Cell
  medium:    auto-approve, direct dispatch
  large:     hold for human decision
  disputed:  escalate to convention (controversial cards)

Size thresholds, approval rules, and timeouts are configurable
via praxis.yaml -> card_gate: section.

Persistence: JSON file via PersistableMixin (self-contained, not coupled to CardRegistry).
Restart-safe: pending approvals + history survive reboot.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum, auto

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.discovery import get_config as _get_config
from l1.kernel.params.agent import CARD_GATE_ARCH_KEYWORDS, SIGNAL_TARGET_L3
from l1.kernel.params.kernel import WitnessStatus
from l1.kernel.params.system import LOG_TRUNC_200
from l1.kernel.paths import get_paths as _gp
from l3._persistable import PersistableMixin
from l3.card.card_unified import CardLifecycle

logger = logging.getLogger(__name__)

# Resolve auto-save interval from config with params fallback
from l1.kernel.params.system import CARD_GATE_AUTO_SAVE as _PARAMS_AUTO_SAVE

_GATE_AUTO_SAVE: float = _PARAMS_AUTO_SAVE
_cfg = _get_config("persistence")
if _cfg:
    _GATE_AUTO_SAVE = float(_cfg.get("card_gate", _GATE_AUTO_SAVE))


class CardSize(Enum):
    """CardSize — enum of SMALL, MEDIUM, LARGE, DISPUTED."""
    SMALL = auto()
    MEDIUM = auto()
    LARGE = auto()
    DISPUTED = auto()


class ApprovalStatus(Enum):
    """ApprovalStatus — enum of PENDING, AUTO_APPROVED, HUMAN_APPROVED, HUMAN_REJECTED...."""
    PENDING = auto()
    AUTO_APPROVED = auto()
    HUMAN_APPROVED = auto()
    HUMAN_REJECTED = auto()
    CONVENTION = auto()


# ── Built-in defaults (overridable via YAML) ──

_DEFAULT_THRESHOLDS: dict[str, int] = {
    "small_max_files": 1,
    "small_max_lines": 50,
    "medium_max_files": 5,
    "medium_max_lines": 200,
    "approval_timeout": 3600,
    "convention_timeout": 7200,
}

_DEFAULT_AUTO_APPROVAL: dict[str, bool] = {
    "small": True,
    "medium": True,
    "large": False,
    "disputed": False,
}


# ── Gate engine with persistence ──

class CardGate(PersistableMixin):
    """Card Gate engine — classify, evaluate, hold, approve, persist."""

    persistence_kind = "card_gate"

    def __init__(self, persist_path: str = ""):
        self._thresholds: dict[str, int] = dict(_DEFAULT_THRESHOLDS)
        self._auto_approval: dict[str, bool] = dict(_DEFAULT_AUTO_APPROVAL)
        self._human_pending: dict[str, dict] = {}
        self._history: list[dict] = []  # approval audit trail
        self._lock = threading.RLock()
        self._init_persistence(persist_path or _gp().card_gate, _GATE_AUTO_SAVE)
        self._restore()
        if _GATE_AUTO_SAVE > 0:
            self._start_auto_save()

    def load_config(self, cfg: dict) -> None:
        if not cfg:
            return
        t = cfg.get("thresholds", {})
        if t:
            self._thresholds.update({k: int(v) for k, v in t.items()
                                      if k in _DEFAULT_THRESHOLDS})
        a = cfg.get("auto_approval", {})
        if a:
            self._auto_approval.update({k: bool(v) for k, v in a.items()
                                         if k in _DEFAULT_AUTO_APPROVAL})
        logger.info("card_gate config loaded")

    # ── Persistence ──

    def _serialize(self) -> dict:
        return {
            "pending": dict(self._human_pending),
            "history": list(self._history),
            "thresholds": dict(self._thresholds),
            "auto_approval": dict(self._auto_approval),
        }

    def _deserialize(self, data: dict) -> bool:
        self._human_pending.clear()
        self._history.clear()
        self._human_pending.update(data.get("pending", {}))
        self._history.extend(data.get("history", []))
        self._thresholds.update(data.get("thresholds", {}))
        self._auto_approval.update(data.get("auto_approval", {}))
        return True

    # ── Public API ──

    @staticmethod
    def _is_architecture_nature(intent: str) -> bool:
        """Detect if card intent describes architecture-scope work."""
        if not intent:
            return False
        lower = intent.lower()
        return any(kw in lower for kw in CARD_GATE_ARCH_KEYWORDS)

    def classify(self, intent: str = "", domain: str = "",
                 file_count: int = 0, estimated_lines: int = 0,
                 has_conflict: bool = False) -> CardSize:
        if has_conflict:
            return CardSize.DISPUTED
        # Architecture-nature cards are always LARGE
        if self._is_architecture_nature(intent):
            return CardSize.LARGE
        if file_count <= self._thresholds["small_max_files"] and estimated_lines <= self._thresholds["small_max_lines"]:
            return CardSize.SMALL
        if file_count <= self._thresholds["medium_max_files"] and estimated_lines <= self._thresholds["medium_max_lines"]:
            return CardSize.MEDIUM
        return CardSize.LARGE

    def _stamp(self, card_id: str, status: str, size: str, by: str) -> None:
        """Stamp approval trail on card record."""
        try:
            from .card_registry import get_registry
            reg = get_registry()
            card = reg._cards.get(card_id)
            if card:
                card.approval_status = status
                card.approval_size = size
                card.approval_at = time.time()
                card.approval_by = by
                if status == "pending":
                    card.lifecycle = CardLifecycle.HOLD
        except Exception:
            logger.debug("card_gate: approval set failed")

    def evaluate(self, card_id: str, intent: str = "", domain: str = "",
                 file_count: int = 0, estimated_lines: int = 0,
                 has_conflict: bool = False) -> dict:
        size = self.classify(intent, domain, file_count, estimated_lines, has_conflict)
        size_name = size.name.lower()
        auto_ok = self._auto_approval.get(size_name, False)

        with self._lock:
            self._history.append({
                "card_id": card_id, "size": size_name,
                "status": ApprovalStatus.AUTO_APPROVED.name if auto_ok else ApprovalStatus.PENDING.name,
                "timestamp": time.time(),
            })
            self._persist()

        if auto_ok:
            self._stamp(card_id, "auto_approved", size_name, "system")
            return {
                "card_id": card_id, "size": size_name,
                "auto_approve": True,
                "status": ApprovalStatus.AUTO_APPROVED.name,
                "action": "dispatch",
            }

        self._stamp(card_id, "pending", size_name, "gate")
        from .card.pending_queue import get_queue
        get_queue().enqueue(card_id, intent=intent, domain=domain, size=size_name)

        emit_signal(EVENT_TASK_ASSIGN, sender="card_gate", target=SIGNAL_TARGET_L3,
                     data={"card_id": card_id, "event": "held_for_approval",
                           "size": size_name, "intent": intent[:LOG_TRUNC_200]})
        return {
            "card_id": card_id, "size": size_name,
            "auto_approve": False,
            "status": ApprovalStatus.PENDING.name,
            "action": "hold" if size_name == "large" else "convention",
        }

    def approve(self, card_id: str, decision: bool = True, response: str = "") -> dict:
        # Delegate to PendingQueue
        from .card.pending_queue import get_queue
        pq = get_queue()
        items = pq.list(status=WitnessStatus.PENDING)
        for item in items:
            if item["card_id"] == card_id:
                if decision:
                    return pq.approve(item["id"], response)
                return pq.reject(item["id"], response)
        return {"success": False, "error": f"card {card_id} not in pending queue"}

    def list_pending(self) -> list[dict]:
        from .card.pending_queue import get_queue
        return get_queue().list(status=WitnessStatus.PENDING)

    def list_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._history)[-limit:]

    def stats(self) -> dict:
        with self._lock:
            return {
                "pending_human": len(self._human_pending),
                "history_count": len(self._history),
                "thresholds": dict(self._thresholds),
                "auto_approval": dict(self._auto_approval),
            }


# ── Singleton ──

_gate: CardGate | None = None


def get_gate() -> CardGate:
    global _gate
    if _gate is None:
        _gate = CardGate()
    return _gate


def load_config(cfg: dict) -> None:
    get_gate().load_config(cfg)


def evaluate(card_id: str, intent: str = "", domain: str = "",
             file_count: int = 0, estimated_lines: int = 0,
             has_conflict: bool = False) -> dict:
    return get_gate().evaluate(card_id, intent, domain, file_count, estimated_lines, has_conflict)


def approve(card_id: str, decision: bool = True, response: str = "") -> dict:
    return get_gate().approve(card_id, decision, response)


def list_pending() -> list[dict]:
    return get_gate().list_pending()


def list_history(limit: int = 50) -> list[dict]:
    return get_gate().list_history(limit)


def stats() -> dict:
    return get_gate().stats()


def reset_gate() -> None:
    global _gate
    _gate = None
