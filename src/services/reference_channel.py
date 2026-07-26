"""ReferenceChannel — pure observability event recorder for Praxis.

Produces structured JSONL datasets from Agent runtime decisions.
Does NOT affect execution — async write, no backpressure, no blocking.

Each event is a self-contained JSON line with SHA-256 content hash,
suitable for downstream training data pipelines (RLHF, DPO, QLoRA).

Events record:
  - tool_calls: allowed, blocked (and which gate rejected)
  - card_lifecycle: submitted, approved, rejected, completed
  - gatechain: per-gate decision with step details
  - human_correction: CORRECT signals from L2 Shell / API
  - convention: deliberation outcomes
  - anomaly: sequence monitor flags

Reference: NOMOS Reference Channel (JSONL + SHA-256, full provenance)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

from kernel.params.system import (
    RC_PATH,
    RC_FLUSH_INTERVAL,
    RC_MAX_EVENTS,
    RC_EXPORT_LIMIT,
)

logger = logging.getLogger(__name__)


class ReferenceChannel:
    """Append-only event recorder. Does not block or modify execution.

    Usage (from any component):
      from services.reference_channel import get_rc
      get_rc().event("tool_call", {
          "tool_name": "write_file", "agent_id": "agent-1",
          "allowed": False, "gate": "gatechain", "reason": "G3 territory block",
      })
    """

    def __init__(self, path: str = "", flush_interval: float = RC_FLUSH_INTERVAL,
                 max_events: int = RC_MAX_EVENTS):
        self._path = path or os.environ.get("PRAXIS_RC_PATH", RC_PATH)
        self._flush_interval = flush_interval
        self._max_events = max_events
        self._buffer: list[str] = []
        self._lock = threading.Lock()
        self._total = 0
        self._last_flush = time.time()
        self._ensure_path()
        self._load_count()

    def _ensure_path(self) -> None:
        d = os.path.dirname(self._path)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

    def _load_count(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, encoding="utf-8") as f:
                    for _ in f:
                        self._total += 1
        except Exception:
            pass

    def event(self, event_type: str, data: dict,
              source: str = "", trace_id: str = "") -> None:
        """Record a single event. Async-friendly, never blocks execution.

        Args:
            event_type: "tool_call" | "card_lifecycle" | "gatechain" |
                        "human_correction" | "convention" | "anomaly"
            data: event payload dict
            source: component name ("tool_pipeline", "card_registry", ...)
            trace_id: optional card trace_id for correlation
        """
        record = {
            "type": event_type,
            "source": source,
            "trace_id": trace_id,
            "timestamp": time.time(),
            "data": data,
        }
        # Content hash for dedup + provenance
        content = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
        record["sha256"] = hashlib.sha256(content.encode()).hexdigest()[:16]
        line = json.dumps(record, ensure_ascii=False, default=str)

        with self._lock:
            self._buffer.append(line)
            self._total += 1
            now = time.time()
            if (len(self._buffer) >= self._max_events
                    or now - self._last_flush >= self._flush_interval):
                self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                for line in self._buffer:
                    f.write(line + "\n")
            self._buffer.clear()
            self._last_flush = time.time()
        except Exception as e:
            logger.warning("rc flush failed: %s", e)

    def flush(self) -> None:
        """Force flush buffered events to disk."""
        with self._lock:
            self._flush()

    # ── Convenience helpers ──

    def tool_call(self, tool_name: str, agent_id: str, allowed: bool,
                  gate: str = "", reason: str = "", args: dict | None = None,
                  trace_id: str = "",
                  predicted_success: bool = True,
                  predicted_summary: str = "") -> None:
        """Record a tool call with optional prediction for causal training.

        Args:
            predicted_success: Did the model expect this to succeed?
            predicted_summary: What the model predicted would happen (free text).

        The triple {predicted_success, actual_allowed, deviation} forms a
        causal chain training sample when aggregated across many calls.
        """
        deviation = ""
        if predicted_success and not allowed:
            deviation = "false_positive_expectation"
        elif not predicted_success and allowed:
            deviation = "false_negative_expectation"
        self.event("tool_call", {
            "tool_name": tool_name, "agent_id": agent_id,
            "allowed": allowed, "gate": gate, "reason": reason,
            "predicted_success": predicted_success,
            "predicted_summary": predicted_summary[:200],
            "deviation": deviation,
            "args_keys": list((args or {}).keys()),
        }, source="tool_pipeline", trace_id=trace_id)

    def card_lifecycle(self, card_id: str, intent: str, state: str,
                       nature: str = "", size: str = "",
                       error: str = "",
                       predicted_state: str = "completed") -> None:
        """Record card lifecycle transition with prediction for causal training."""
        deviation = ""
        if predicted_state == "completed" and state in ("failed", "cancelled"):
            deviation = "completion_mismatch"
        elif predicted_state == "failed" and state == "completed":
            deviation = "unexpected_completion"
        self.event("card_lifecycle", {
            "card_id": card_id, "intent": intent[:100],
            "state": state, "nature": nature, "size": size,
            "error": error[:100],
            "predicted_state": predicted_state,
            "deviation": deviation,
        }, source="card_registry", trace_id=card_id)

    def human_correction(self, card_id: str, agent_id: str,
                         field: str, old_value: str,
                         new_value: str, reason: str = "") -> None:
        self.event("human_correction", {
            "card_id": card_id, "agent_id": agent_id,
            "field": field, "old_preview": str(old_value)[:200],
            "new_preview": str(new_value)[:200], "reason": reason[:200],
        }, source="l2_shell", trace_id=card_id)

    def anomaly(self, card_id: str, detection: dict,
                cell_id: str = "") -> None:
        self.event("anomaly", {
            "card_id": card_id, "cell_id": cell_id,
            "detection": detection,
        }, source="sequence_monitor", trace_id=card_id)

    def convention(self, card_id: str, outcome: str,
                   participants: list[str], summary: str = "") -> None:
        self.event("convention", {
            "card_id": card_id, "outcome": outcome,
            "participant_count": len(participants),
            "summary": summary[:200],
        }, source="convention", trace_id=card_id)

    # ── Export ──

    def export(self, limit: int = 1000, offset: int = 0,
               event_type: str = "") -> list[dict]:
        """Read events from disk. Pure query, no side effects."""
        results: list[dict] = []
        try:
            if not os.path.exists(self._path):
                return results
            with open(self._path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i < offset:
                        continue
                    if len(results) >= limit:
                        break
                    try:
                        ev = json.loads(line.strip())
                        if event_type and ev.get("type") != event_type:
                            continue
                        results.append(ev)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("rc export: %s", e)
        return results

    def count(self, event_type: str = "") -> int:
        if event_type:
            return len(self.export(limit=RC_EXPORT_LIMIT, event_type=event_type))
        return self._total

    def stats(self) -> dict:
        return {
            "path": self._path,
            "total_events": self._total,
            "buffered": len(self._buffer),
            "max_events_per_flush": self._max_events,
            "flush_interval_s": self._flush_interval,
        }


# ── Global singleton (no init needed — lazy on first event) ──

_rc: ReferenceChannel | None = None
_rc_lock = threading.Lock()


def get_rc() -> ReferenceChannel:
    global _rc
    if _rc is None:
        with _rc_lock:
            if _rc is None:
                _rc = ReferenceChannel()
    return _rc


def reset_rc() -> None:
    global _rc
    if _rc is not None:
        _rc.flush()
    _rc = None
