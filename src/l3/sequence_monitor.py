"""SequenceMonitor — per-Cell tool call sequence anomaly detection.

Built into each Cell as an independent module. Tracks n-gram transition
probabilities of tool calls per card execution. Flags sequences whose
transition probability falls below a configurable threshold.

This catches the "each step legal, sequence is attack" class of threats
that single-call gates (GateChain, constitution) cannot detect.

Architecture:
  Per-Cell singleton. Each Cell gets its own monitor instance.
  N-gram model: P(next_tool | previous_N_tools).
  Trained online from actual card executions (unsupervised).
  Detection: compare live sequence against historical distribution.

Thread-safe. Persistable to JSON for restart safety.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from typing import Any

from l1.kernel.params.system import (
    SEQ_MONITOR_PATH,
    SEQ_MONITOR_NGRAM,
    SEQ_MONITOR_MIN_SAMPLES,
    SEQ_MONITOR_ANOMALY_THRESHOLD,
)

logger = logging.getLogger(__name__)


class SequenceMonitor:
    """Per-Cell tool call sequence anomaly detector.

    Usage:
      monitor = SequenceMonitor(cell_id="cell-1")
      monitor.record(["read_file", "write_file", "shell"])  # after card completes
      result = monitor.evaluate(["read_file", "shell"])       # before/during card
      # → {"probability": 0.02, "anomaly": True, "reason": "low_transition"}
    """

    def __init__(self, cell_id: str = "default",
                 ngram: int = SEQ_MONITOR_NGRAM,
                 min_samples: int = SEQ_MONITOR_MIN_SAMPLES,
                 anomaly_threshold: float = SEQ_MONITOR_ANOMALY_THRESHOLD,
                 persist_path: str = ""):
        self.cell_id = cell_id
        self._ngram_n = ngram
        self._min_samples = min_samples
        self._anomaly_threshold = anomaly_threshold
        self._persist_path = persist_path or os.environ.get(
            "PRAXIS_SEQ_MONITOR_PATH",
            f".praxis_seq_monitor_{cell_id}.json",
        )
        # n-gram transition count table
        # {("read_file",): {"write_file": 42, "shell": 3}, ...}
        self._transitions: dict[tuple[str, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._total_sequences: int = 0
        self._total_calls: int = 0
        self._lock = threading.RLock()
        self._load()

    # ── Training: record a completed sequence ──

    def record(self, tool_names: list[str]) -> dict:
        """Record a completed tool call sequence (from one card execution).

        Updates the n-gram transition probability table.
        Returns sequence stats.
        """
        if not tool_names or len(tool_names) < 2:
            return {"recorded": False, "reason": "too_short", "length": len(tool_names)}

        with self._lock:
            for i in range(1, len(tool_names)):
                # Build n-gram context from previous n-1 calls
                for n in range(1, min(self._ngram_n, i) + 1):
                    context = tuple(tool_names[i - n:i])
                    next_tool = tool_names[i]
                    self._transitions[context][next_tool] += 1
            self._total_sequences += 1
            self._total_calls += len(tool_names)
        self._save()
        return {"recorded": True, "tools": len(tool_names), "total_sequences": self._total_sequences}

    # ── Detection: evaluate a live sequence ──

    def evaluate(self, tool_names: list[str]) -> dict:
        """Evaluate a tool call sequence for anomalies.

        Returns dict with:
          - probability: geometric mean of transition probabilities
          - anomaly: True if below threshold
          - transitions: per-step detail
        """
        if len(tool_names) < 2:
            return {"probability": 1.0, "anomaly": False, "transitions": []}

        step_details = []
        probs: list[float] = []

        with self._lock:
            for i in range(1, len(tool_names)):
                context, next_tool = tool_names[:i], tool_names[i]
                best_prob = 0.0
                best_context = ""
                for n in range(1, min(self._ngram_n, i) + 1):
                    ctx = tuple(tool_names[i - n:i])
                    counts = self._transitions.get(ctx, {})
                    total = sum(counts.values())
                    if total >= self._min_samples:
                        p = counts.get(next_tool, 0) / total
                        if p > best_prob:
                            best_prob = p
                            best_context = "|".join(ctx)

                prob = best_prob if best_prob > 0 else 0.0
                probs.append(prob)
                step_details.append({
                    "step": i,
                    "tool": next_tool,
                    "context": best_context,
                    "probability": round(prob, 4),
                    "known": prob > 0,
                })

        # Overall probability: geometric mean
        if not probs:
            return {"probability": 1.0, "anomaly": False, "transitions": []}
        import math as _m
        product = _m.prod(max(p, 1e-10) for p in probs)
        geo_mean = product ** (1.0 / len(probs))
        anomaly = geo_mean < self._anomaly_threshold

        return {
            "probability": round(geo_mean, 4),
            "anomaly": anomaly,
            "reason": "low_transition_probability" if anomaly else "",
            "transitions": step_details,
            "total_sequences": self._total_sequences,
        }

    # ── Query ──

    def transition_prob(self, context: list[str], next_tool: str) -> float:
        """Get P(next_tool | context)."""
        ctx = tuple(context)
        with self._lock:
            counts = self._transitions.get(ctx, {})
            total = sum(counts.values())
            if total < self._min_samples:
                return 0.0
            return counts.get(next_tool, 0) / total

    def top_transitions(self, context: list[str], top_n: int = 5) -> list[dict]:
        """Get most likely next tools for a context."""
        ctx = tuple(context)
        with self._lock:
            counts = dict(self._transitions.get(ctx, {}))
        total = sum(counts.values())
        if total < self._min_samples:
            return []
        sorted_tools = sorted(counts.items(), key=lambda x: -x[1])
        return [
            {"tool": t, "count": c, "probability": round(c / total, 3)}
            for t, c in sorted_tools[:top_n]
        ]

    def stats(self) -> dict:
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "total_sequences": self._total_sequences,
                "total_calls": self._total_calls,
                "ngram_n": self._ngram_n,
                "min_samples": self._min_samples,
                "anomaly_threshold": self._anomaly_threshold,
                "contexts": len(self._transitions),
            }

    def reset(self) -> None:
        with self._lock:
            self._transitions.clear()
            self._total_sequences = 0
            self._total_calls = 0
        if os.path.exists(self._persist_path):
            try:
                os.remove(self._persist_path)
            except Exception:
                pass

    # ── Persistence ──

    def _save(self) -> None:
        try:
            data = {
                "cell_id": self.cell_id,
                "ngram_n": self._ngram_n,
                "total_sequences": self._total_sequences,
                "total_calls": self._total_calls,
                "transitions": {
                    "|".join(k): v for k, v in self._transitions.items()
                },
            }
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._persist_path)
        except Exception as e:
            logger.warning("seq_monitor save: %s", e)

    def _load(self) -> None:
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self._total_sequences = data.get("total_sequences", 0)
            self._total_calls = data.get("total_calls", 0)
            for ctx_str, counts in data.get("transitions", {}).items():
                ctx = tuple(ctx_str.split("|"))
                self._transitions[ctx] = defaultdict(int, counts)
        except Exception as e:
            logger.warning("seq_monitor load: %s", e)


# ── Per-Cell singleton registry ──

_instances: dict[str, SequenceMonitor] = {}
_instances_lock = threading.Lock()


def get_monitor(cell_id: str = "default",
                ngram: int = 0, min_samples: int = 0,
                anomaly_threshold: float = 0.0) -> SequenceMonitor:
    with _instances_lock:
        if cell_id not in _instances:
            _instances[cell_id] = SequenceMonitor(
                cell_id=cell_id,
                ngram=ngram or SEQ_MONITOR_NGRAM,
                min_samples=min_samples or SEQ_MONITOR_MIN_SAMPLES,
                anomaly_threshold=anomaly_threshold or SEQ_MONITOR_ANOMALY_THRESHOLD,
            )
        return _instances[cell_id]


def reset_monitor(cell_id: str = "") -> None:
    with _instances_lock:
        if cell_id:
            inst = _instances.pop(cell_id, None)
            if inst:
                inst.reset()
        else:
            for inst in _instances.values():
                inst.reset()
            _instances.clear()
