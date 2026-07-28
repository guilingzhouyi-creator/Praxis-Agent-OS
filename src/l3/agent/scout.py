"""Scout — lightweight LLM agent for read-only investigation.

Each Scout is an independent LLM session agent, not a subprocess command runner.
Scouts can understand natural language instructions and use Ring 1 read-only tools.

Design:
  - Scout is spawned by a Peer Agent with a natural language task description
  - Scout has its own LLM session (lightweight, short-lived)
  - Scout can ONLY use Ring 1 tools (read_file, grep_search, etc.)
  - GateChain enforces read-only at G1 (tool whitelist)
  - Scout completes the task, produces a report, then terminates
  - No state is retained after termination

Compared to Peer Agent:
  Peer Agent: full LLM session, Ring 1/2.5/3 tools, persistent, has ACB
  Scout:      lightweight LLM session, Ring 1 only, temporary, no ACB
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.agent import SCOUT_LOOP_STEPS, SCOUT_LOOP_TIMEOUT, SCOUT_FINDING_TRUNC, SCOUT_RESULT_TRUNC, SCOUT_FILE_READ_TRUNC
from l1.kernel.params.kernel import RUN_SUBPROCESS_TIMEOUT
from l1.kernel.params.system import SCOUT_MONITOR_INTERVAL, SCOUT_CACHE_TTL, SCOUT_CACHE_MAX_ENTRIES, MAX_SCOUTS_PER_AGENT, SCOUT_TIMEOUT, SCOUT_POOL_MAX

from l3.services.model_service import get_service as _get_model_service
from l3.tool_system.tool_spec import ToolRing, execute_tool_spec, get_tool

logger = logging.getLogger(__name__)




@dataclass
class ScoutReport:
    scout_id: str
    agent_id: str
    task: str = ""
    status: str = "running"   # running | done | timeout | error
    findings: list[dict] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    error: str = ""
    started_at: float = field(default_factory=time.time)
    elapsed: float = 0.0


class ScoutSession:
    """A lightweight LLM agent session for investigation.

    The Scout has its own LLM context, but can only use Ring 1 tools.
    It receives a natural language task, executes tool calls, and produces a report.
    """

    def __init__(self, scout_id: str, agent_id: str, task: str):
        self.scout_id = scout_id
        self.agent_id = agent_id
        self.task = task
        self.report = ScoutReport(scout_id=scout_id, agent_id=agent_id, task=task)
        self._done = threading.Event()

    def execute(self) -> ScoutReport:
        """Execute the scout task using Ring 1 tools only."""
        try:
            result = self._investigate_autonomous()
            self.report.findings = result.get("findings", [])
            self.report.output = result.get("steps", [])
            self.report.status = "done"
        except Exception as e:
            self.report.status = "error"
            self.report.error = str(e)
        self.report.elapsed = time.time() - self.report.started_at
        self._done.set()
        return self.report

    def _investigate_autonomous(self) -> dict:
        """LLM-driven autonomous investigation via AgentLoop."""
        from .agent_loop import AgentLoop
        loop = AgentLoop(task=self.task, agent_id=self.agent_id, prompt_key="scout.system")

        # Register Ring 1 tools with real implementations
        loop.add_tool("read_file", "Read file contents", {"path": "string"},
                      self._tool_read)
        loop.add_tool("grep_search", "Search for pattern in files",
                      {"pattern": "string", "path": "string"}, self._tool_grep)
        loop.add_tool("list_dir", "List directory contents", {"path": "string"},
                      self._tool_list)

        result = loop.run(max_steps=SCOUT_LOOP_STEPS, timeout=SCOUT_LOOP_TIMEOUT,
                          **_get_model_service().resolve_dict(_MODEL_SPEC))
        findings = []

        # Extract answer
        answer = result.get("answer", "")
        if answer:
            findings.append({"type": "conclusion", "content": answer[:SCOUT_FINDING_TRUNC]})

        # Extract tool call results
        for step in result.get("steps", []):
            action = step.get("action", "")
            if action.startswith("tool:"):
                findings.append({
                    "type": action,
                    "args": step.get("args", {}),
                    "result": str(step.get("result", ""))[:SCOUT_RESULT_TRUNC],
                    "elapsed": step.get("elapsed", 0),
                })

        return {"success": True, "findings": findings, "steps": result.get("steps", [])}

    # ── Real tool implementations for autonomous investigation ──

    def _tool_read(self, args: dict, agent_id: str = "") -> dict:
        path = args.get("path", "")
        if not path:
            return {"success": False, "error": "path required"}
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {"success": True, "data": content[:SCOUT_FILE_READ_TRUNC], "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _tool_grep(self, args: dict, agent_id: str = "") -> dict:
        import subprocess as _sp
        from l1.kernel.platform import grep_cmd as _grep_cmd
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        try:
            cmd = _grep_cmd(pattern, path, max_count=20)
            r = _sp.run(cmd, capture_output=True, text=True, timeout=RUN_SUBPROCESS_TIMEOUT)
            out = (r.stdout or "")[:SCOUT_FILE_READ_TRUNC]
            return {"success": True, "data": out} if out else {"success": True, "data": "no matches"}
        except FileNotFoundError:
            return {"success": False, "error": "grep tool not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _tool_list(self, args: dict, agent_id: str = "") -> dict:
        import os as _os
        path = args.get("path", ".")
        try:
            entries = _os.listdir(path)
            return {"success": True, "data": entries[:SCOUT_FILE_READ_TRUNC // 40], "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": str(e)}


import os  # needed for _try_symbols and _try_path_from_task

# Lazy import to avoid circular import with services._base
from l3._base import BaseService
from l1.kernel.platform import grep_cmd as _grep_cmd

_MODEL_SPEC = "scout"


class ScoutPool(BaseService):
    """Scout pool — manages LLM agent scout lifecycle.

    Pool model:
      max_per_agent: 3  concurrent scouts per agent
      max_total: 12      total pool size
      scouts are idle-warmed, but only activate LLM session on commission
    """

    def __init__(self, min_idle: int = 2, max_total: int = SCOUT_POOL_MAX,
                 max_per_agent: int = MAX_SCOUTS_PER_AGENT,
                 idle_timeout: float = 60.0, session_timeout: float = SCOUT_TIMEOUT):
        super().__init__("scout")
        self.min_idle = min_idle
        self.max_total = max_total
        self.max_per_agent = max_per_agent
        self.idle_timeout = idle_timeout
        self.session_timeout = session_timeout
        self._idle: list[ScoutSession] = []
        self._active: dict[str, ScoutSession] = {}
        self._agent_active: dict[str, int] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._running = True
        self._total_commissioned = 0
        self._cache: dict[str, dict] = {}
        self._cache_order: list[str] = []  # LRU ordering
        self._cache_hits = 0
        self._cache_misses = 0
        threading.Thread(target=self._scaler, daemon=True).start()

    def _on_start(self) -> dict:
        return {"success": True, "pool_size": self.max_total}

    def _on_stop(self) -> dict:
        self._running = False
        return {"success": True}

    def commission(self, agent_id: str, task: str, scope: dict | None = None,
                   cell_id: str = "") -> dict:
        """Commission a scout with a natural language investigation task.

        The scout gets its own LLM session, investigates using Ring 1 tools,
        and returns a report.

        Args:
            cell_id: If set, successful findings are also injected into the
                     Cell's L2 cache for cross-agent sharing.
        """
        # Check cache
        cache_key = hashlib.md5(f"{agent_id}:{task}".encode()).hexdigest()
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        with self._lock:
            agent_active = self._agent_active.get(agent_id, 0)
            if agent_active >= self.max_per_agent:
                return {"success": False, "error": f"max scouts ({self.max_per_agent}) reached for {agent_id}"}
            total_active = len(self._active)
            if total_active >= self.max_total:
                return {"success": False, "error": f"scout pool full ({self.max_total})"}

            scout_id = f"scout-{agent_id}-{self._next_id}"
            self._next_id += 1
            scout = ScoutSession(scout_id, agent_id, task)
            self._active[scout_id] = scout
            self._agent_active[agent_id] = agent_active + 1
            self._total_commissioned += 1

        # Execute in background thread
        thread = threading.Thread(target=self._run_scout, args=(scout_id,), daemon=True)
        thread.start()

        # Wait for result with timeout
        scout._done.wait(timeout=self.session_timeout)
        if not scout._done.is_set():
            scout.report.status = "timeout"
            scout.report.error = f"scout timed out after {self.session_timeout}s"

        result = {
            "success": scout.report.status == "done",
            "scout_id": scout_id,
            "task": task,
            "status": scout.report.status,
            "findings": scout.report.findings,
            "output": scout.report.output,
            "error": scout.report.error,
            "elapsed": round(scout.report.elapsed, 3),
        }

        # Cache result
        self._set_cached(cache_key, result)

        # Inject findings into Cell L2 cache if cell_id provided
        if cell_id and result.get("success") and result.get("findings"):
            try:
                from l3.cell import get_cell as _get_cell
                cell = _get_cell(cell_id)
                findings_text = str(result["findings"])[:SCOUT_FINDING_TRUNC]
                cell.cache.inject(
                    key=f"scout:{agent_id}:{task[:40]}",
                    value=result["findings"],
                    summary=f"Scout [{agent_id}]: {len(result['findings'])} findings — {findings_text[:150]}",
                    agent_id=agent_id,
                    entry_type="scout_result",
                    importance=0.5,
                )
            except Exception:
                pass  # best-effort

        return result

    def _run_scout(self, scout_id: str) -> None:
        """Run the scout in background."""
        scout = self._active.get(scout_id)
        if not scout:
            return
        try:
            scout.execute()
        except Exception as e:
            scout.report.status = "error"
            scout.report.error = str(e)
        finally:
            with self._lock:
                self._agent_active[scout.agent_id] = max(0, self._agent_active.get(scout.agent_id, 0) - 1)
                self._active.pop(scout_id, None)

    def get(self, scout_id: str) -> dict:
        with self._lock:
            for s in self._idle:
                if s.scout_id == scout_id:
                    return {"success": True, "scout_id": scout_id, "status": "idle"}
            s = self._active.get(scout_id)
            if s:
                return {"success": True, "scout_id": scout_id, "status": s.report.status,
                        "findings": s.report.findings, "elapsed": s.report.elapsed}
        return {"success": False, "error": "scout not found"}

    def stats(self) -> dict:
        with self._lock:
            return {
                "idle": len(self._idle), "active": len(self._active),
                "max_total": self.max_total, "max_per_agent": self.max_per_agent,
                "per_agent": dict(self._agent_active),
                "total_commissioned": self._total_commissioned,
                "cache": {
                    "entries": len(self._cache),
                    "max": SCOUT_CACHE_MAX_ENTRIES,
                    "hits": self._cache_hits,
                    "misses": self._cache_misses,
                    "hit_rate": round(self._cache_hits / max(self._cache_hits + self._cache_misses, 1) * 100, 1),
                },
            }

    def _get_cached(self, key: str) -> dict | None:
        entry = self._cache.get(key)
        if entry and time.time() - entry["ts"] < SCOUT_CACHE_TTL:
            self._cache_hits += 1
            # Move to end (LRU)
            if key in self._cache_order:
                self._cache_order.remove(key)
            self._cache_order.append(key)
            return entry["result"]
        self._cache_misses += 1
        return None

    def _set_cached(self, key: str, result: dict) -> None:
        if key not in self._cache:
            self._cache_order.append(key)
        self._cache[key] = {"result": result, "ts": time.time()}
        while len(self._cache) > SCOUT_CACHE_MAX_ENTRIES:
            oldest = self._cache_order.pop(0)
            self._cache.pop(oldest, None)

    def _scaler(self) -> None:
        while self._running:
            time.sleep(SCOUT_MONITOR_INTERVAL)


_pool: ScoutPool | None = None


def scout_cache_get(template: str, scope: dict | None, ttl: float = 30.0) -> dict | None:
    """Module-level cache lookup — delegates to pool's cache."""
    import hashlib, json
    raw = template + "|" + json.dumps(scope or {}, sort_keys=True)
    key = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return get_pool()._get_cached(key)


def scout_cache_set(template: str, scope: dict | None, result: dict, ttl: float = 30.0) -> None:
    """Module-level cache store — delegates to pool's cache."""
    import hashlib, json
    raw = template + "|" + json.dumps(scope or {}, sort_keys=True)
    key = hashlib.sha256(raw.encode()).hexdigest()[:16]
    get_pool()._set_cached(key, result)


def scout_cache_clear() -> None:
    get_pool()._cache.clear()


def scout_cache_stats() -> dict:
    pool = get_pool()
    total = pool._cache_hits + pool._cache_misses
    return {
        "entries": len(pool._cache),
        "max": SCOUT_CACHE_MAX_ENTRIES,
        "hits": pool._cache_hits,
        "misses": pool._cache_misses,
        "hit_rate": round(pool._cache_hits / max(total, 1) * 100, 1),
    }


def get_pool() -> ScoutPool:
    global _pool
    if _pool is None:
        _pool = ScoutPool()
    return _pool


def reset_pool() -> None:
    global _pool
    if _pool:
        _pool.stop()
    _pool = None