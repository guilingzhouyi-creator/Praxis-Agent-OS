"""GateChain kernel module — G1-G5 tool authorization.

Architecture:
  G1: Tool whitelist (must be in TOOL_REGISTRY)
  G2: Identity (agent must have a valid proof)
  G3: Territory + risk scoring (ACP-based dynamic scoring)
  G4: Escalation (Ring 2.5 pool, Ring 3 approval)
  G5: Composite judgment (full context + history)

  All gates run in sequence.  Any BLOCK stops execution.
  No tool call bypasses GateChain.

Usage:
  gate = get_gatechain()
  result = gate.check("my_tool", "my_agent", target="/project/foo.py")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from .params.kernel import (
    GATECHAIN_DANGER_LEVELS,
    GATECHAIN_DANGER_WEIGHT,
    GATECHAIN_DEFAULT_DANGER,
    GATECHAIN_ESCALATION_DANGER,
    GATECHAIN_FREQ_MULTIPLIER,
    GATECHAIN_FREQ_WEIGHT,
    GATECHAIN_G1_INDEX,
    GATECHAIN_G3_INDEX,
    GATECHAIN_G5_HISTORY_LIMIT,
    GATECHAIN_HIGH_FREQ_THRESHOLD,
    GATECHAIN_HISTORY_WEIGHT,
    GATECHAIN_L3_TARGET,
    GATECHAIN_PATTERN_TEMPLATE,
    GATECHAIN_REP_HIGH_THRESHOLD,
    GATECHAIN_REP_LOW_THRESHOLD,
    GATECHAIN_REPEAT_THRESHOLD,
    GATECHAIN_RISK_WARN_THRESHOLD,
    GATECHAIN_SENDER,
    GATECHAIN_TOOLS_KEY,
    LEDGER_COUNT_WINDOW,
    LEDGER_MAX_ENTRIES,
    LEDGER_RECENT_LIMIT,
)

logger = logging.getLogger(__name__)

# ── Stagnation callback (registered at boot from L3 wiring) ──
# Avoids direct ``from l3.agent.stagnation import ...`` in kernel layer.
_stagnation_callback: Callable | None = None


def register_stagnation_callback(fn: Callable | None) -> None:
    """Register a break_loop callback (called by G5 on repeated-tool detection).

    The callback receives (agent_id, pattern) and returns a dict with
    ``action`` / ``reason`` keys. Registered at boot from L3 wiring.
    """
    global _stagnation_callback
    _stagnation_callback = fn


def _break_loop(agent_id: str, pattern: str) -> dict:
    if _stagnation_callback is None:
        return {"action": "", "reason": "stagnation module unavailable"}
    try:
        return _stagnation_callback(agent_id, {"pattern": pattern}) or {}
    except Exception as e:
        logger.warning("kernel/gatechain: break_loop failed: %s", e)
        return {"action": "", "reason": str(e)}


class GateResult(Enum):
    """GateResult — enum of gate result variants."""
    PASS = auto()
    WARN = auto()
    BLOCK = auto()
    REPORT = auto()


class PatternKey(Enum):
    """PatternKey — enum of pattern key variants."""
    TERRITORY = auto()
    FREQUENCY = auto()
    DANGER = auto()
    COOLDOWN = auto()
    HISTORY = auto()


@dataclass
class LedgerEntry:
    """LedgerEntry — ledger entry record (agent_id, tool, target, result, timestamp)."""
    agent_id: str
    tool: str
    target: str
    result: GateResult
    timestamp: float = field(default_factory=time.time)
    pattern: str = ""


class ToolHistoryLedger:
    """Stores recent tool call history for G3/G5 risk analysis.

    Uses dict-based buckets for O(1) lookup by agent/tool instead of
    linear scan of the full list.
    """

    def __init__(self, max_entries: int = LEDGER_MAX_ENTRIES):
        self._max = max_entries
        self._entries: list[LedgerEntry] = []
        self._by_agent: dict[str, deque[LedgerEntry]] = {}
        self._by_tool: dict[str, deque[LedgerEntry]] = {}
        self._by_agent_tool: dict[str, deque[LedgerEntry]] = {}
        self._lock = threading.Lock()

    def _bucket_key(self, agent_id: str, tool: str) -> str:
        return f"{agent_id}|{tool}"

    def record(self, entry: LedgerEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max:
                self._entries = self._entries[-self._max:]
            # Update index buckets
            self._by_agent.setdefault(entry.agent_id, deque(maxlen=self._max)).append(entry)
            self._by_tool.setdefault(entry.tool, deque(maxlen=self._max)).append(entry)
            key = self._bucket_key(entry.agent_id, entry.tool)
            self._by_agent_tool.setdefault(key, deque(maxlen=self._max)).append(entry)

    def recent(self, agent_id: str = "", tool: str = "", limit: int = LEDGER_RECENT_LIMIT) -> list[LedgerEntry]:
        """Get recent entries for an agent/tool. Uses indexed buckets for O(bucket) lookup."""
        with self._lock:
            if agent_id and tool:
                key = self._bucket_key(agent_id, tool)
                bucket = self._by_agent_tool.get(key, [])
                return list(bucket)[-limit:]
            if agent_id:
                bucket = self._by_agent.get(agent_id, [])
                return list(bucket)[-limit:]
            if tool:
                bucket = self._by_tool.get(tool, [])
                return list(bucket)[-limit:]
            return self._entries[-limit:]

    def count(self, agent_id: str = "", tool: str = "", window: float = LEDGER_COUNT_WINDOW) -> int:
        """Count entries within a time window. Scans only the relevant bucket."""
        now = time.time()
        with self._lock:
            if agent_id and tool:
                key = self._bucket_key(agent_id, tool)
                bucket = self._by_agent_tool.get(key, [])
            elif agent_id:
                bucket = self._by_agent.get(agent_id, [])
            elif tool:
                bucket = self._by_tool.get(tool, [])
            else:
                bucket = self._entries
            return sum(1 for e in bucket if (now - e.timestamp) <= window)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._by_agent.clear()
            self._by_tool.clear()
            self._by_agent_tool.clear()



class GateChain:
    """G1-G5 gate chain — non-bypassable tool pre-authorization.

    Gates are pluggable: call ``register_gate()`` to add or replace gates.
    Each gate receives ``(tool, agent_id, target, territory, territory_map,
    reputation, steps, overall, ledger)`` and returns ``(steps, overall)``.
    """

    def __init__(self):
        self.ledger = ToolHistoryLedger()
        self._lock = threading.Lock()
        self._known_tools: set[str] = set()
        self._territories: dict[str, list[str]] = {}
        self._gates: list[tuple[str, Callable]] = list(_BUILTIN_GATES)

    def register_tools(self, tool_names: list[str]) -> None:
        with self._lock:
            self._known_tools.update(tool_names)

    def set_territories(self, territories: dict[str, list[str]]) -> None:
        with self._lock:
            self._territories.update(territories)

    def register_gate(self, name: str, fn: Callable,
                      index: int | None = None) -> None:
        """Register a gate check.  Insert at *index* (default: append)."""
        entry = (name, fn)
        with self._lock:
            if index is not None:
                self._gates.insert(index, entry)
            else:
                self._gates.append(entry)

    def check(self, tool: str, agent_id: str, target: str = "",
              territory: list[str] | None = None,
              territory_map: dict[str, list[str]] | None = None,
              reputation: float = -1.0,
              danger: int | None = None) -> dict:
        """Run G1-G5 gate checks.

        Args:
            danger: Optional override for the tool's danger level.
                    If None, uses GATECHAIN_DANGER_LEVELS from params.
                    Set by ApprovalPolicy in the tool pipeline.
        """
        steps: list[dict] = []
        overall = GateResult.PASS
        context = {
            "tool": tool, "agent_id": agent_id, "target": target,
            "territory": territory, "territory_map": territory_map,
            "reputation": reputation, "steps": steps,
            "danger_override": danger,
        }
        for name, fn in self._gates:
            if overall == GateResult.BLOCK:
                break
            try:
                steps, overall = fn(context, self)
            except Exception as e:
                # Fail closed: a gate that crashed cannot vouch for the
                # call, so we treat it as a BLOCK instead of silently
                # continuing with the previous (likely PASS) overall.
                logger.warning("kernel/gatechain: gate %s raised: %s — blocking", name, e)
                steps.append({"gate": name, "result": "BLOCK",
                              "reason": f"gate crashed: {e}"})
                overall = GateResult.BLOCK
                break

        final = overall.name
        g1 = steps[GATECHAIN_G1_INDEX]["result"] if len(steps) > 0 else "?"
        g3 = steps[GATECHAIN_G3_INDEX]["result"] if len(steps) > 2 else "?"
        self.ledger.record(LedgerEntry(
            agent_id=agent_id, tool=tool, target=target,
            result=overall, pattern=GATECHAIN_PATTERN_TEMPLATE.format(g1=g1, g3=g3),
        ))
        return {"allowed": overall != GateResult.BLOCK, "decision": final, "steps": steps}


# ── Built-in gate functions ──

def _gate_g1(ctx: dict, gc: GateChain) -> tuple[list[dict], GateResult]:
    steps: list[dict] = ctx["steps"]
    overall: GateResult = ctx.get("_overall", GateResult.PASS)
    known = gc._known_tools or (ctx.get("territory_map") or {}).get(GATECHAIN_TOOLS_KEY, set())
    if not known:
        steps.append({"gate": "G1", "result": "WARN", "reason": "no whitelist configured"})
        return steps, GateResult.WARN
    if ctx["tool"] not in known:
        steps.append({"gate": "G1", "result": "BLOCK", "reason": "tool not in whitelist"})
        return steps, GateResult.BLOCK
    steps.append({"gate": "G1", "result": "PASS"})
    return steps, overall


def _gate_g2(ctx: dict, gc: GateChain) -> tuple[list[dict], GateResult]:
    steps: list[dict] = ctx["steps"]
    overall: GateResult = ctx.get("_overall", GateResult.PASS)
    from .process import get_table
    pcb = get_table().get_by_name(ctx["agent_id"]) if ctx["agent_id"] else None
    if not pcb:
        steps.append({"gate": "G2", "result": "BLOCK",
                      "reason": f"agent '{ctx['agent_id']}' not registered in process table"})
        return steps, GateResult.BLOCK
    if pcb.state.name not in ("READY", "RUNNING"):
        steps.append({"gate": "G2", "result": "BLOCK",
                      "reason": f"agent state is {pcb.state.name}, not READY/RUNNING"})
        return steps, GateResult.BLOCK
    if not pcb.identity_verified:
        steps.append({"gate": "G2", "result": "WARN",
                      "reason": f"agent '{ctx['agent_id']}' has no Ed25519 keypair (identity not verified)"})
        return steps, GateResult.WARN
    steps.append({"gate": "G2", "result": "PASS", "pid": pcb.pid, "ring": pcb.ring})
    return steps, overall


def _gate_g3(ctx: dict, gc: GateChain) -> tuple[list[dict], GateResult]:
    steps: list[dict] = ctx["steps"]
    overall: GateResult = ctx.get("_overall", GateResult.PASS)
    override = ctx.get("danger_override")
    if override is not None:
        danger = override
    else:
        from l1.kernel.discovery import get_config
        danger_levels = get_config("gatechain_danger_levels") or GATECHAIN_DANGER_LEVELS
        danger = danger_levels.get(ctx["tool"], GATECHAIN_DEFAULT_DANGER)
    if ctx["target"] and ctx["territory"]:
        in_territory = any(ctx["target"].startswith(t) for t in ctx["territory"])
        if not in_territory:
            steps.append({"gate": "G3", "result": "BLOCK",
                          "reason": f"tool call target '{ctx['target']}' is outside card scope {ctx['territory']}"})
            return steps, GateResult.BLOCK
    recent_count = gc.ledger.count(ctx["agent_id"], ctx["tool"], window=LEDGER_COUNT_WINDOW)
    risk_score = danger + (recent_count * GATECHAIN_FREQ_MULTIPLIER)
    if risk_score >= GATECHAIN_RISK_WARN_THRESHOLD:
        steps.append({"gate": "G3", "result": "WARN", "risk_score": risk_score})
        ctx["_overall"] = GateResult.WARN
    else:
        steps.append({"gate": "G3", "result": "PASS", "risk_score": risk_score})
    ctx["_danger"] = danger
    return steps, ctx.get("_overall", overall)


def _gate_g4(ctx: dict, gc: GateChain) -> tuple[list[dict], GateResult]:
    steps: list[dict] = ctx["steps"]
    overall: GateResult = ctx.get("_overall", GateResult.PASS)
    danger = ctx.get("_danger", 0)
    if danger >= GATECHAIN_ESCALATION_DANGER:
        from .event import Signal, SignalType, get_bus
        get_bus().emit(Signal(type=SignalType.REVIEW_REQUESTED,
                               sender=GATECHAIN_SENDER, target=GATECHAIN_L3_TARGET,
                               data={"tool": ctx["tool"], "agent_id": ctx["agent_id"],
                                     "target": ctx["target"], "danger": danger}))
        steps.append({"gate": "G4", "result": "WARN",
                      "reason": f"danger={danger}, L3 notified"})
    else:
        steps.append({"gate": "G4", "result": "PASS"})
    return steps, overall


def _gate_g5(ctx: dict, gc: GateChain) -> tuple[list[dict], GateResult]:
    steps: list[dict] = ctx["steps"]
    overall: GateResult = ctx.get("_overall", GateResult.PASS)
    from .reputation import get_reputation
    rep = ctx["reputation"] if ctx["reputation"] >= 0 else get_reputation().get(ctx["agent_id"])
    history = gc.ledger.recent(ctx["agent_id"], limit=GATECHAIN_G5_HISTORY_LIMIT)
    same_tool_count = sum(1 for e in history if e.tool == ctx["tool"])
    repeated = len(history) >= GATECHAIN_REPEAT_THRESHOLD
    high_freq_same_tool = same_tool_count >= GATECHAIN_HIGH_FREQ_THRESHOLD
    danger = ctx.get("_danger", 0)
    score = (danger * GATECHAIN_DANGER_WEIGHT
             + (len(history) * GATECHAIN_HISTORY_WEIGHT)
             + (same_tool_count * GATECHAIN_FREQ_WEIGHT))
    g3_result = next((s["result"] for s in steps if s.get("gate") == "G3"), "PASS")
    if rep >= GATECHAIN_REP_HIGH_THRESHOLD and g3_result == "WARN":
        steps.append({"gate": "G5", "result": "PASS",
                      "reason": f"high reputation ({rep:.2f}) tolerates G3 warn, score={score:.1f}",
                      "reputation": round(rep, 2)})
    elif rep < GATECHAIN_REP_LOW_THRESHOLD and g3_result == "WARN":
        steps.append({"gate": "G5", "result": "BLOCK",
                      "reason": f"low reputation ({rep:.2f}) + risk, score={score:.1f}",
                      "reputation": round(rep, 2)})
        return steps, GateResult.BLOCK
    elif repeated and high_freq_same_tool:
        _ba = _break_loop(ctx["agent_id"], "SPINNING")
        steps.append({"gate": "G5", "result": "REPORT",
                      "reason": f"{len(history)} calls, {same_tool_count}x '{ctx['tool']}', rep={rep:.2f}, score={score:.1f}",
                      "break_action": _ba.get("action", ""),
                      "break_reason": _ba.get("reason", "")})
        return steps, GateResult.REPORT
    elif repeated:
        _ba = _break_loop(ctx["agent_id"], "OSCILLATION")
        outcome = "REPORT" if rep < GATECHAIN_REP_LOW_THRESHOLD else "WARN"
        steps.append({"gate": "G5", "result": outcome,
                      "reason": f"{len(history)} calls, rep={rep:.2f}, score={score:.1f}",
                      "reputation": round(rep, 2),
                      "break_action": _ba.get("action", ""),
                      "break_reason": _ba.get("reason", "")})
        if outcome == "REPORT":
            return steps, GateResult.REPORT
    else:
        steps.append({"gate": "G5", "result": "PASS", "score": score,
                      "reputation": round(rep, 2)})
    return steps, overall


_BUILTIN_GATES: list[tuple[str, Callable]] = [
    ("G1", _gate_g1), ("G2", _gate_g2), ("G3", _gate_g3),
    ("G4", _gate_g4), ("G5", _gate_g5),
]


_gatechain: GateChain | None = None
_gatechain_lock = threading.Lock()


def get_gatechain() -> GateChain:
    """Get the GateChain singleton."""
    global _gatechain
    if _gatechain is None:
        with _gatechain_lock:
            if _gatechain is None:
                _gatechain = GateChain()
    return _gatechain


def reset_gatechain() -> None:
    global _gatechain
    _gatechain = None
