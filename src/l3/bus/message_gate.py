"""MessageGate — dependency-aware message policy engine for MonitorBus.

Each rule defines a pattern, an action, and optional dependency chain.
Rules are evaluated by priority order when a MonitorEvent is emitted.

Actions:
  allow    — let the event through (default)
  block    — discard the event silently
  mute     — store but exclude from API query results
  hold     — queue the event pending dependency resolution
  redirect — forward to an alternate consumer (webhook/SSE channel)

Dependency chain: Gate B's action only applies while Gate A is active.
Active duration is controlled by hold_timeout on the dependency gate.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.agent import CARD_GATE_APPROVAL_TIMEOUT
from .monitor_bus import MonitorEvent
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)


@dataclass
class MessageGateRule:
    """A single message gate rule with dependency support."""
    id: str
    pattern: dict  # {"type": "network.peer.loss", "severity": "crit", "agent_id": ""} — empty fields match any
    action: str    # "allow" | "block" | "mute" | "hold" | "redirect"
    depends_on: list[str] = field(default_factory=list)
    priority: int = 5
    reason: str = ""
    redirect_target: str = ""
    hold_timeout: float = CARD_GATE_APPROVAL_TIMEOUT
    created_at: float = field(default_factory=time.time)

    def matches(self, event: MonitorEvent) -> bool:
        from .monitor_bus import _match_type
        for key in ("type", "severity", "agent_id", "cell_id", "source"):
            val = self.pattern.get(key, "")
            if not val:
                continue
            if key == "type":
                if not _match_type(event.type, val):
                    return False
            elif getattr(event, key, "") != val:
                return False
        return True


class MessageGateEngine(PersistableMixin):
    """Message gate engine — rules + dependency chain resolution."""

    persistence_kind = "message_gate"

    def __init__(self, persist_path: str = ""):
        self._rules: dict[str, MessageGateRule] = {}
        self._triggered: dict[str, float] = {}  # rule_id → triggered_at
        self._lock = threading.RLock()
        from l1.kernel.paths import get_paths as _gp
        self._init_persistence(persist_path or _gp().message_gate_state)
        self._restore()

    # ── Rule management ──

    def add(self, rule: MessageGateRule) -> None:
        with self._lock:
            self._rules[rule.id] = rule
            self._persist()

    def remove(self, rule_id: str) -> bool:
        with self._lock:
            if rule_id not in self._rules:
                return False
            del self._rules[rule_id]
            self._triggered.pop(rule_id, None)
            self._persist()
            return True

    def list_rules(self) -> list[dict]:
        with self._lock:
            return [{"id": r.id, "pattern": r.pattern, "action": r.action,
                     "depends_on": r.depends_on, "priority": r.priority,
                     "reason": r.reason, "hold_timeout": r.hold_timeout}
                    for r in self._rules.values()]

    # ── Evaluation ──

    def evaluate(self, event: MonitorEvent) -> str:
        """Evaluate event against rules. Returns action string."""
        with self._lock:
            matched = []
            # Sort by priority DESCENDING so the highest-priority rule wins.
            for rule in sorted(self._rules.values(), key=lambda r: r.priority, reverse=True):
                if not rule.matches(event):
                    continue
                if not self._deps_met(rule):
                    continue
                matched.append(rule)

            if not matched:
                return "allow"

            best = matched[0]
            self._triggered[best.id] = time.time()
            self._persist()

        if best.action in ("block", "mute"):
            logger.info("message_gate: %s %s by %s", best.action, event.type, best.id)
        return best.action

    def _deps_met(self, rule: MessageGateRule) -> bool:
        for dep_id in rule.depends_on:
            dep_triggered = self._triggered.get(dep_id)
            if dep_triggered is None:
                return False
            dep_rule = self._rules.get(dep_id)
            if dep_rule and (time.time() - dep_triggered) > dep_rule.hold_timeout:
                return False
        return True

    # ── Persistence ──

    def _serialize(self) -> dict:
        return {
            "rules": {rid: {"id": r.id, "pattern": r.pattern, "action": r.action,
                            "depends_on": r.depends_on, "priority": r.priority,
                            "reason": r.reason, "hold_timeout": r.hold_timeout}
                      for rid, r in self._rules.items()},
            "triggered": self._triggered,
        }

    def _deserialize(self, data: dict) -> bool:
        self._rules.clear()
        for rid, d in data.get("rules", {}).items():
            self._rules[rid] = MessageGateRule(
                id=d["id"], pattern=d["pattern"], action=d["action"],
                depends_on=d.get("depends_on", []), priority=d.get("priority", 5),
                reason=d.get("reason", ""), hold_timeout=d.get("hold_timeout", CARD_GATE_APPROVAL_TIMEOUT),
            )
        self._triggered.update(data.get("triggered", {}))
        return True

    def to_dict(self) -> dict:
        return {"rules": self.list_rules(), "triggered_count": len(self._triggered)}


# ── Singleton ──

_gate: MessageGateEngine | None = None


def get_gate() -> MessageGateEngine:
    global _gate
    if _gate is None:
        _gate = MessageGateEngine()
    return _gate


def reset_gate() -> None:
    global _gate
    _gate = None
