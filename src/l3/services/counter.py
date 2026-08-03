"""Cell-level unified counters — tokens, tool calls, AgentLoop turns.

All counters are per-agent, aggregated to Cell total.
Designed for TUI display: every method returns plain dicts.

Endpoints:
  GET /api/tokens     → token usage (input/output/cache hit per agent)
  GET /api/tools      → tool call statistics (calls/success/failure per tool)
  GET /api/loops      → AgentLoop turn statistics

Integration:
  Token counting:  auto-wired via llm.py @on_llm_call("post") hook
  Tool counting:   call record_tool_call() from tool_pipeline or execute_tool_spec
  Loop counting:   call record_loop() from agent_loop.run() result
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class CellCounter:
    """Per-agent counters aggregated to Cell level."""

    def __init__(self):
        self._lock = threading.RLock()
        # Token usage: agent_id → list of {ts, input, output, cache_hit, cache_miss, model}
        self._tokens: dict[str, list[dict]] = defaultdict(list)
        # Tool calls: agent_id → list of {ts, tool, success, elapsed}
        self._tools: dict[str, list[dict]] = defaultdict(list)
        # AgentLoop turns: agent_id → list of {ts, turns, steps, elapsed}
        self._loops: dict[str, list[dict]] = defaultdict(list)
        # All loops chronologically (flat, for recent query)
        self._all_loops: list[dict] = []

    # ── Record ──

    def record_token(self, agent_id: str, input_tokens: int = 0,
                     output_tokens: int = 0, cache_hit: int = 0,
                     cache_miss: int = 0, model: str = "") -> None:
        entry = {
            "ts": time.time(),
            "input": input_tokens, "output": output_tokens,
            "total": input_tokens + output_tokens,
            "cache_hit": cache_hit, "cache_miss": cache_miss, "model": model,
        }
        with self._lock:
            self._tokens[agent_id].append(entry)

    def record_tool(self, agent_id: str, tool: str,
                    success: bool, elapsed: float = 0.0) -> None:
        entry = {"ts": time.time(), "tool": tool,
                 "success": success, "elapsed": round(elapsed, 3)}
        with self._lock:
            self._tools[agent_id].append(entry)

    def record_loop(self, agent_id: str, turns: int,
                    steps: int, elapsed: float = 0.0,
                    loop_id: str = "", trace: list[dict] | None = None,
                    side: dict | None = None) -> None:
        """Record an AgentLoop execution with optional trace details."""
        entry = {"ts": time.time(), "turns": turns, "loop_id": loop_id or "",
                 "steps": steps, "elapsed": round(elapsed, 3),
                 "trace": trace or [], "side": side or {}}
        with self._lock:
            self._loops[agent_id].append(entry)
            self._all_loops.append(entry)
            if len(self._all_loops) > 500:
                self._all_loops = self._all_loops[-500:]

    # ── Token queries ──

    def token_rate(self, window: float = 60.0) -> dict:
        """Token consumption rate over the last N seconds.

        Returns tokens/minute for each agent + Cell total.
        Designed for TUI real-time dashboards (poll every few seconds).
        """
        now = time.time()
        cutoff = now - window
        with self._lock:
            all_entries = [(aid, e) for aid, entries in self._tokens.items() for e in entries]
        recent = [(aid, e) for aid, e in all_entries if e["ts"] >= cutoff]
        if not recent:
            return {"window_s": window, "tokens_per_min": 0, "by_agent": {}}
        by_agent: dict[str, int] = {}
        total = 0
        for aid, e in recent:
            t = e.get("total", e.get("input", 0) + e.get("output", 0))
            by_agent[aid] = by_agent.get(aid, 0) + t
            total += t
        minutes = window / 60.0
        return {
            "window_s": window,
            "tokens_per_min": round(total / max(minutes, 0.01)),
            "calls_in_window": len(recent),
            "by_agent": {aid: {"tokens": v, "tokens_per_min": round(v / max(minutes, 0.01))}
                         for aid, v in by_agent.items()},
        }

    def token_summary(self, agent_id: str = "") -> dict:
        with self._lock:
            ids = [agent_id] if agent_id else list(self._tokens.keys())
        result = {}
        for aid in ids:
            entries = list(self._tokens.get(aid, []))
            if not entries:
                result[aid] = {"calls": 0}
                continue
            total_input = sum(e["input"] for e in entries)
            total_output = sum(e["output"] for e in entries)
            ch = sum(e["cache_hit"] for e in entries)
            cm = sum(e["cache_miss"] for e in entries)
            result[aid] = {
                "calls": len(entries),
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "cache_hit_tokens": ch,
                "cache_miss_tokens": cm,
                "cache_hit_rate": round(ch / max(ch + cm, 1) * 100, 1),
                "avg_tokens_per_call": round((total_input + total_output) / max(len(entries), 1), 1),
            }
        return result if not agent_id else result.get(agent_id, {"calls": 0})

    # ── Tool call queries ──

    def tool_summary(self, agent_id: str = "") -> dict:
        with self._lock:
            ids = [agent_id] if agent_id else list(self._tools.keys())
        result = {}
        for aid in ids:
            entries = list(self._tools.get(aid, []))
            if not entries:
                result[aid] = {"total": 0}
                continue
            by_tool: dict[str, dict] = {}
            for e in entries:
                t = e["tool"]
                s = by_tool.setdefault(t, {"calls": 0, "success": 0, "failure": 0, "total_elapsed": 0.0})
                s["calls"] += 1
                if e["success"]:
                    s["success"] += 1
                else:
                    s["failure"] += 1
                s["total_elapsed"] += e["elapsed"]
            result[aid] = {
                "total": len(entries),
                "by_tool": {t: {**s, "avg_elapsed": round(s["total_elapsed"] / max(s["calls"], 1), 3)}
                            for t, s in by_tool.items()},
            }
        return result if not agent_id else result.get(agent_id, {"total": 0})

    # ── AgentLoop turn queries ──

    def loop_summary(self, agent_id: str = "") -> dict:
        with self._lock:
            ids = [agent_id] if agent_id else list(self._loops.keys())
        result = {}
        for aid in ids:
            entries = list(self._loops.get(aid, []))
            if not entries:
                result[aid] = {"total": 0}
                continue
            total_turns = sum(e["turns"] for e in entries)
            total_steps = sum(e["steps"] for e in entries)
            total_elapsed = sum(e["elapsed"] for e in entries)
            side_total: dict[str, float] = {}
            for e in entries:
                for k, v in (e.get("side") or {}).items():
                    side_total[k] = side_total.get(k, 0.0) + float(v)
            result[aid] = {
                "total": len(entries),
                "total_turns": total_turns,
                "total_steps": total_steps,
                "total_elapsed": round(total_elapsed, 2),
                "avg_turns_per_loop": round(total_turns / max(len(entries), 1), 1),
                "avg_steps_per_turn": round(total_steps / max(total_turns, 1), 1),
                "avg_elapsed_per_loop": round(total_elapsed / max(len(entries), 1), 2),
                "side": {k: round(v, 3) for k, v in side_total.items()},
            }
        return result if not agent_id else result.get(aid, {"total": 0})

    # ── Cell total (all agents aggregated) ──

    def cell_total(self) -> dict:
        agents = set()
        with self._lock:
            agents.update(self._tokens.keys())
            agents.update(self._tools.keys())
            agents.update(self._loops.keys())
        return {
            "agents": sorted(agents),
            "tokens": self.token_summary(),
            "tools": self.tool_summary(),
            "loops": self.loop_summary(),
        }

    # ── Structured export for monitoring ──

    def export_json(self, agent_id: str = "",
                    window: float = 0.0,
                    include_raw: bool = False) -> dict:
        """Export all counters as a structured JSON blob.

        Args:
            agent_id: Filter to specific agent (empty = all)
            window: Time window in seconds (0 = all time)
            include_raw: Include raw event lists (may be large)

        Returns:
            dict with metadata + token/tool/loop sections
        """
        cutoff = time.time() - window if window > 0 else 0
        result = {
            "exported_at": time.time(),
            "window": window,
            "agent_filter": agent_id,
            "tokens": {},
            "tools": {},
            "loops": {},
            "summary": self.summary(),
        }

        with self._lock:
            # Token export
            for aid, data in self._tokens.items():
                if agent_id and aid != agent_id:
                    continue
                entry = {
                    "input": data.get("input", 0),
                    "output": data.get("output", 0),
                    "cache_hit": data.get("cache_hit", 0),
                    "total": data.get("input", 0) + data.get("output", 0),
                }
                if include_raw and "events" in data:
                    entry["events"] = [e for e in data["events"]
                                       if e.get("ts", 0) >= cutoff]
                result["tokens"][aid] = entry

            # Tool export
            for aid, tools in self._tools.items():
                if agent_id and aid != agent_id:
                    continue
                tool_data = {}
                for tname, tinfo in tools.items():
                    entry = {
                        "calls": tinfo.get("calls", 0),
                        "success": tinfo.get("success", 0),
                        "failure": tinfo.get("failure", 0),
                        "last_call": tinfo.get("last_call", 0),
                    }
                    if include_raw and "events" in tinfo:
                        entry["events"] = [e for e in tinfo["events"]
                                           if e.get("ts", 0) >= cutoff]
                    tool_data[tname] = entry
                result["tools"][aid] = tool_data

            # Loop export
            for aid, data in self._loops.items():
                if agent_id and aid != agent_id:
                    continue
                entry = {
                    "total_turns": data.get("total_turns", 0),
                    "total_steps": data.get("total_steps", 0),
                    "total_elapsed": data.get("total_elapsed", 0.0),
                    "average_elapsed": 0.0,
                }
                if entry["total_turns"] > 0:
                    entry["average_elapsed"] = round(
                        entry["total_elapsed"] / entry["total_turns"], 3
                    )
                if include_raw and "turns" in data:
                    entry["turns"] = [t for t in data["turns"]
                                      if t.get("ts", 0) >= cutoff]
                result["loops"][aid] = entry

        return result

    def export_metrics(self) -> list[dict]:
        """Export time-series metrics for Prometheus-style scraping.

        Returns a flat list of metric dicts with name/labels/value.
        """
        metrics = []
        with self._lock:
            for aid, data in self._tokens.items():
                metrics.append({"name": "praxis_tokens_input_total",
                                "labels": {"agent": aid},
                                "value": data.get("input", 0)})
                metrics.append({"name": "praxis_tokens_output_total",
                                "labels": {"agent": aid},
                                "value": data.get("output", 0)})
            for aid, tools in self._tools.items():
                for tname, tinfo in tools.items():
                    metrics.append({"name": "praxis_tool_calls_total",
                                    "labels": {"agent": aid, "tool": tname},
                                    "value": tinfo.get("calls", 0)})
                    metrics.append({"name": "praxis_tool_failures_total",
                                    "labels": {"agent": aid, "tool": tname},
                                    "value": tinfo.get("failure", 0)})
            for aid, data in self._loops.items():
                metrics.append({"name": "praxis_loop_turns_total",
                                "labels": {"agent": aid},
                                "value": data.get("total_turns", 0)})
        return metrics


_counter: CellCounter | None = None


def get_counter() -> CellCounter:
    global _counter
    if _counter is None:
        _counter = CellCounter()
    return _counter


def reset_counter() -> None:
    global _counter
    _counter = None
