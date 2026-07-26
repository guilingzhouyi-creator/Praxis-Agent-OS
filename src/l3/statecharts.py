"""Statecharts — 5 orthogonal regions for Agent lifecycle, persistable.

Agent OS spec §1.2:
  Task:     IDLE → EXECUTING → AWAIT_REVIEW → DONE/ERROR
  Health:   HEALTHY → DEGRADED → UNRESPONSIVE → CRASHED
  Review:   NOT_UNDER_REVIEW → UNDER_REVIEW → PASSED/REJECTED
  Resource: NORMAL → TOKEN_LOW → MEMORY_HIGH → THROTTLED
  Comm:     CONNECTED → DEGRADED → DISCONNECTED → ISOLATED

Persistence: JSON via save_snapshot() / restore_snapshot().
"""

from __future__ import annotations

import os
import json
import time
import logging
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

from l1.kernel.params.system import STATECHARTS_PATH, STATECHARTS_AUTO_SAVE

logger = logging.getLogger(__name__)


class EventType(Enum):
    TASK_ASSIGN = auto(); TASK_CANCEL = auto()
    ANALYSIS_DONE = auto(); CHANGES_DONE = auto()
    SELF_CHECK_PASS = auto(); SELF_CHECK_FAIL = auto()
    REVIEW_PASSED = auto(); REVIEW_REJECTED = auto()
    FIXES_DONE = auto(); CONVERGENCE_DONE = auto()
    DIRECT_START = auto(); DIRECT_END = auto()
    TOOL_CALL_FAIL = auto(); TOOL_CALL_SUCCESS = auto()
    HEARTBEAT_TIMEOUT = auto(); HEARTBEAT_RESTORED = auto()
    AGENT_CRASHED = auto()
    REVIEW_REQUESTED = auto()
    TOKEN_EXCEEDED = auto(); MEMORY_EXCEEDED = auto()
    BUDGET_RESET = auto(); MEMORY_RECOVERED = auto()
    COMM_CONNECT = auto(); COMM_DEGRADE = auto()
    COMM_DISCONNECT = auto(); COMM_RECONNECT = auto()
    COMM_ISOLATE = auto()
    TIMEOUT = auto()


@dataclass
class Transition:
    to: str; reason: str = ""; ctx: dict = field(default_factory=dict)

@dataclass
class EventCtx:
    type: EventType; data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class Region(ABC):
    name: str = ""; state: str = ""; parent: str | None = None
    history: dict[str, str] = {}
    _transitions: dict = {}
    broadcast: Callable | None = None

    def _add(self, s, e, t, r=""): self._transitions[(s, e)] = Transition(to=t, reason=r)
    def _add_any(self, e, t, r=""): self._transitions[("*", e)] = Transition(to=t, reason=r)

    def handle(self, event):
        key = (self.state, event.type)
        tr = self._transitions.get(key)
        if tr: return self._apply(tr, event)
        tr = self._transitions.get(("*", event.type))
        if tr: return self._apply(tr, event)
        return None

    def _apply(self, tr, event):
        if self.parent: self.history[self.parent] = self.state
        self.state = tr.to; tr.ctx = {**event.data, **tr.ctx}
        return tr


class TaskRegion(Region):
    name = "Task"
    def __init__(self):
        self.state = "IDLE"
        self._add("IDLE", EventType.TASK_ASSIGN, "COMMISSIONED")
        self._add("COMMISSIONED", EventType.TASK_CANCEL, "IDLE")
        self._add("COMMISSIONED", EventType.ANALYSIS_DONE, "ANALYZING")
        self._add("ANALYZING", EventType.ANALYSIS_DONE, "MODIFYING")
        self._add("MODIFYING", EventType.CHANGES_DONE, "VERIFYING")
        self._add("VERIFYING", EventType.SELF_CHECK_PASS, "WAITING")
        self._add("VERIFYING", EventType.SELF_CHECK_FAIL, "RETRYABLE")
        self._add("WAITING", EventType.REVIEW_PASSED, "DONE")
        self._add("WAITING", EventType.REVIEW_REJECTED, "FIXING")
        self._add("FIXING", EventType.FIXES_DONE, "WAITING")
        self._add("RETRYABLE", EventType.TASK_ASSIGN, "ANALYZING")
        self._add_any(EventType.TASK_CANCEL, "IDLE")
        self._add_any(EventType.AGENT_CRASHED, "INTERRUPTED")

    @property
    def is_active(self): return self.state not in ("IDLE", "DONE")


class HealthRegion(Region):
    name = "Health"
    def __init__(self, ft=3, st=5, hto=15, cto=30):
        self.state = "HEALTHY"
        self.ft, self.st, self.hto, self.cto = ft, st, hto, cto
        self._fc = self._sc = 0; self._lh = time.time()
        self._add("DEGRADED", EventType.HEARTBEAT_TIMEOUT, "UNRESPONSIVE")
        self._add("UNRESPONSIVE", EventType.HEARTBEAT_RESTORED, "HEALTHY")
        self._add("UNRESPONSIVE", EventType.AGENT_CRASHED, "CRASHED")
        self._add("CRASHED", EventType.HEARTBEAT_RESTORED, "HEALTHY")

    def handle(self, event):
        if event.type == EventType.TOOL_CALL_FAIL:
            self._fc += 1; self._sc = 0
            if self.state == "HEALTHY" and self._fc >= self.ft:
                self._fc = 0; return self._apply(Transition(to="DEGRADED"), event)
        elif event.type == EventType.TOOL_CALL_SUCCESS:
            self._sc += 1; self._fc = 0
            if self.state == "DEGRADED" and self._sc >= self.st:
                self._sc = 0; return self._apply(Transition(to="HEALTHY"), event)
        elif event.type == EventType.HEARTBEAT_TIMEOUT:
            el = time.time() - self._lh
            if self.state in ("DEGRADED","UNRESPONSIVE") and el > self.cto:
                return self._apply(Transition(to="CRASHED"), event)
            if self.state not in ("UNRESPONSIVE","CRASHED"):
                return self._apply(Transition(to="UNRESPONSIVE"), event)
        if event.type in (EventType.TOOL_CALL_FAIL, EventType.TOOL_CALL_SUCCESS,
                          EventType.HEARTBEAT_TIMEOUT, EventType.HEARTBEAT_RESTORED):
            return None
        return super().handle(event)

    def heartbeat(self): self._lh = time.time()
    @property
    def is_healthy(self): return self.state == "HEALTHY"
    @property
    def is_alive(self): return self.state != "CRASHED"


class ReviewRegion(Region):
    name = "Review"
    def __init__(self):
        self.state = "NOT_UNDER_REVIEW"
        self._reviewers = []; self._votes = {}
        self._add("NOT_UNDER_REVIEW", EventType.REVIEW_REQUESTED, "UNDER_REVIEW")
        self._add("UNDER_REVIEW", EventType.REVIEW_PASSED, "REVIEW_PASSED")
        self._add("UNDER_REVIEW", EventType.REVIEW_REJECTED, "REVIEW_REJECTED")
        self._add("UNDER_REVIEW", EventType.COMM_DISCONNECT, "REVIEW_PASSED", "auto-pass")
        self._add("UNDER_REVIEW", EventType.TIMEOUT, "REVIEW_PASSED", "timeout")
        self._add("REVIEW_PASSED", EventType.TASK_ASSIGN, "NOT_UNDER_REVIEW")
        self._add("REVIEW_REJECTED", EventType.TASK_ASSIGN, "NOT_UNDER_REVIEW")

    def add_reviewer(self, rid):
        if rid not in self._reviewers: self._reviewers.append(rid)
    def vote(self, rid, ok):
        self._votes[rid] = ok
        if not ok: return {"action": "rejected", "by": rid}
        if len(self._votes) >= len(self._reviewers) and all(self._votes.values()):
            return {"action": "passed"}
        return {"action": "pending", "remaining": len(self._reviewers) - len(self._votes)}
    @property
    def is_under_review(self): return self.state == "UNDER_REVIEW"


class ResourceRegion(Region):
    name = "Resource"
    def __init__(self, tb=73000, ml=500):
        self.state = "NORMAL"
        self.tb, self.ml = tb, ml
        self.tc = self.mu = 0
        self._add("NORMAL", EventType.TOKEN_EXCEEDED, "TOKEN_LOW")
        self._add("NORMAL", EventType.MEMORY_EXCEEDED, "MEMORY_HIGH")
        self._add("TOKEN_LOW", EventType.BUDGET_RESET, "NORMAL")
        self._add("TOKEN_LOW", EventType.TOKEN_EXCEEDED, "THROTTLED")
        self._add("THROTTLED", EventType.BUDGET_RESET, "NORMAL")
        self._add("MEMORY_HIGH", EventType.MEMORY_RECOVERED, "NORMAL")
    @property
    def usage_pct(self): return round(self.tc / self.tb * 100, 1)
    @property
    def is_throttled(self): return self.state == "THROTTLED"


class CommRegion(Region):
    name = "Comm"
    def __init__(self, dt=10.0, dst=30.0):
        self.state = "CONNECTED"
        self.dt, self.dst = dt, dst
        self._latency = 0.0; self._ra = 0
        self._add("CONNECTED", EventType.COMM_DEGRADE, "DEGRADED")
        self._add("CONNECTED", EventType.COMM_DISCONNECT, "DISCONNECTED")
        self._add("DEGRADED", EventType.COMM_CONNECT, "CONNECTED")
        self._add("DEGRADED", EventType.COMM_DISCONNECT, "DISCONNECTED")
        self._add("DEGRADED", EventType.COMM_ISOLATE, "ISOLATED")
        self._add("DISCONNECTED", EventType.COMM_RECONNECT, "CONNECTED")
        self._add("DISCONNECTED", EventType.TIMEOUT, "ISOLATED")
        self._add("ISOLATED", EventType.COMM_RECONNECT, "CONNECTED")
    @property
    def is_connected(self): return self.state == "CONNECTED"
    @property
    def is_isolated(self): return self.state == "ISOLATED"


class AgentStatecharts:
    def __init__(self, agent_id="", persist_path=""):
        self.agent_id = agent_id
        self.task = TaskRegion(); self.health = HealthRegion()
        self.review = ReviewRegion(); self.resource = ResourceRegion()
        self.comm = CommRegion()
        self._regions = [self.task, self.health, self.review, self.resource, self.comm]
        self._persist_path = persist_path or STATECHARTS_PATH.replace(".json", f"_{agent_id}.json") if agent_id else STATECHARTS_PATH
        self._restore_snapshot()

    def save_snapshot(self) -> dict:
        data = {
            "agent_id": self.agent_id,
            "_version": 1,
            "regions": {},
        }
        for r in self._regions:
            rdata = {"state": r.state}
            if hasattr(r, "_reviewers"):
                rdata["_reviewers"] = list(r._reviewers)
            if hasattr(r, "_votes"):
                rdata["_votes"] = dict(r._votes)
            if hasattr(r, "tc"):
                rdata["tc"] = r.tc
            if hasattr(r, "mu"):
                rdata["mu"] = r.mu
            if hasattr(r, "_fc"):
                rdata["_fc"] = r._fc
            if hasattr(r, "_sc"):
                rdata["_sc"] = r._sc
            if hasattr(r, "_lh"):
                rdata["_lh"] = r._lh
            if hasattr(r, "_latency"):
                rdata["_latency"] = r._latency
            if hasattr(r, "_ra"):
                rdata["_ra"] = r._ra
            data["regions"][r.name] = rdata
        try:
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._persist_path)
            return {"success": True}
        except Exception as e:
            logger.warning("statecharts save %s: %s", self.agent_id, e)
            return {"success": False, "error": str(e)}

    def _restore_snapshot(self) -> None:
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("_version", 0) < 1:
                return
            regions_data = data.get("regions", {})
            for r in self._regions:
                rd = regions_data.get(r.name)
                if rd is None:
                    continue
                if "state" in rd:
                    r.state = rd["state"]
                if hasattr(r, "_reviewers") and "_reviewers" in rd:
                    r._reviewers = list(rd["_reviewers"])
                if hasattr(r, "_votes") and "_votes" in rd:
                    r._votes = dict(rd["_votes"])
                if hasattr(r, "tc") and "tc" in rd:
                    r.tc = rd["tc"]
                if hasattr(r, "mu") and "mu" in rd:
                    r.mu = rd["mu"]
                if hasattr(r, "_fc") and "_fc" in rd:
                    r._fc = rd["_fc"]
                if hasattr(r, "_sc") and "_sc" in rd:
                    r._sc = rd["_sc"]
                if hasattr(r, "_lh") and "_lh" in rd:
                    r._lh = rd["_lh"]
                if hasattr(r, "_latency") and "_latency" in rd:
                    r._latency = rd["_latency"]
                if hasattr(r, "_ra") and "_ra" in rd:
                    r._ra = rd["_ra"]
        except Exception as e:
            logger.warning("statecharts restore %s: %s", self.agent_id, e)

    def dispatch(self, et, data=None):
        ctx = EventCtx(type=et, data=data or {})
        trs = []
        for r in self._regions:
            tr = r.handle(ctx)
            if tr: trs.append(tr)
        if et == EventType.AGENT_CRASHED:
            self.task.handle(EventCtx(type=EventType.AGENT_CRASHED, data={"checkpoint": True}))
        return trs

    @property
    def snapshot(self): return {r.name: r.state for r in self._regions}
    @property
    def is_active(self): return self.task.is_active and self.health.is_alive
    def __repr__(self):
        return f"Statecharts({self.agent_id}): " + " | ".join(f"{r.name}={r.state}" for r in self._regions)