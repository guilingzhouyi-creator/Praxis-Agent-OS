"""L3ASubAgentPool — async subagent pool for L3A sessions.

L3A spawns two kinds of subagents:
  - card-planner:   read_file + grep + cardwrite → produces CardUnified
  - investigator:   read-only, returns structured findings

All subagents run in L3A's own thread pool (not Cell SubAgentPool).
Results collected via group-based l3a_collect (blocking wait).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from . import params as _p
from . import pipeline as _pipeline
from .types import L3ATask, L3ATaskGroup
from l3.error_bus import capture
from l1.kernel.params.system import LOG_TRUNC_200, LOG_TRUNC_2000

logger = logging.getLogger(__name__)

_SID_LEN = 8
_SPAWN_PREFIX = "sa"

_L3A_SPECS: dict[str, dict] = {
    "card-planner": {
        "allowed_tools": ["read_file", "grep_search", "list_dir", "glob", "cardwrite"],
        "max_steps": _p.SA_CARD_PLANNER_MAX_STEPS,
        "timeout": _p.SA_CARD_PLANNER_TIMEOUT,
        "expect_keys": ["domain", "card_nature", "phases", "tasks", "findings"],
    },
    "investigator": {
        "allowed_tools": ["read_file", "grep_search", "list_dir", "glob"],
        "max_steps": _p.SA_INVESTIGATOR_MAX_STEPS,
        "timeout": _p.SA_INVESTIGATOR_TIMEOUT,
        "expect_keys": ["findings", "files_examined", "summary"],
    },
}


class L3ASubAgentPool:
    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="l3a-sa")
        self._tasks: dict[str, L3ATask] = {}
        self._groups: dict[str, L3ATaskGroup] = {}
        self._lock = threading.RLock()

    def commission(self, spec: str, task: str, group: str = "",
                   expect: dict | None = None) -> dict:
        if spec not in _L3A_SPECS:
            return {"success": False, "error": f"unknown spec: {spec}"}
        tid = f"{_SPAWN_PREFIX}-{uuid.uuid4().hex[:_SID_LEN]}"
        task_obj = L3ATask(
            task_id=tid, spec=spec, task=task,
            group=group, expect=expect, status="pending",
        )
        with self._lock:
            self._tasks[tid] = task_obj
            if group:
                if group not in self._groups:
                    self._groups[group] = L3ATaskGroup(group_id=group)
                self._groups[group].task_ids.append(tid)
        fut = self._executor.submit(self._run, tid, spec, task)
        task_obj.future = fut
        task_obj.status = "running"
        logger.debug("l3a subagent: spawned %s (%s) group=%s", tid, spec, group)
        return {"success": True, "task_id": tid, "spec": spec, "group": group}

    def collect(self, group: str, timeout: float = 30.0) -> dict:
        t0 = time.time()
        with self._lock:
            grp = self._groups.get(group)
            if not grp:
                return {"success": False, "error": f"unknown group: {group}"}
            tids = list(grp.task_ids)
        futures = []
        with self._lock:
            for tid in tids:
                t = self._tasks.get(tid)
                if t and t.future:
                    futures.append(t.future)
        remaining = timeout
        deadline = time.time() + timeout
        results = []
        for fut in as_completed(futures):
            now = time.time()
            if now >= deadline:
                break
            try:
                fut.result(timeout=deadline - now)
            except Exception:
                # Task failed/timed out — status already recorded on the task object.
                pass
        with self._lock:
            for tid in tids:
                t = self._tasks.get(tid)
                results.append({
                    "task_id": tid,
                    "spec": t.spec if t else "",
                    "status": t.status if t else "unknown",
                    "result": t.result if t else None,
                })
        elapsed = time.time() - t0
        return {"success": True, "group": group, "results": results,
                "count": len(results), "elapsed": round(elapsed, 2)}

    def peek(self, task_id: str) -> dict:
        with self._lock:
            t = self._tasks.get(task_id)
        if not t:
            return {"success": False, "error": f"unknown task: {task_id}"}
        return {"success": True, "task_id": task_id, "spec": t.spec,
                "status": t.status, "result": t.result}

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
        logger.debug("l3a subagent pool: shut down")

    def _resolve_tool_handler(self, tool_name: str):
        if tool_name == "cardwrite":
            from .helpers import cardwrite_handler
            return cardwrite_handler
        try:
            from l3.tool_system.tool_spec import get_tool as _gt
            spec = _gt(tool_name)
            if spec and spec.handler:
                return spec.handler
        except Exception:
            capture("l3a subagent: tool handler resolve failed", error_code="E_L3A_SA", component="l3a")
            pass
        return None

    def _run(self, task_id: str, spec_name: str, task_text: str) -> dict:
        spec = _L3A_SPECS.get(spec_name, {})
        max_steps = spec.get("max_steps", 6)
        timeout = spec.get("timeout", 45.0)
        allowed_tools = spec.get("allowed_tools", [])
        t0 = time.time()

        try:
            from l3.agent.agent_loop import AgentLoop
            agent_id = f"l3a-sa-{task_id[:_SID_LEN]}"
            loop = AgentLoop(
                task=task_text,
                agent_id=agent_id,
                role="l3a_subagent",
                system=f"You are a {spec_name} subagent for L3A. "
                       f"Use allowed tools: {', '.join(allowed_tools)}. "
                       "Return structured results as JSON in your final answer.",
                prompt_key="l3a.agentloop_system",
            )

            registered = set()
            for tn in allowed_tools:
                if tn in registered:
                    continue
                handler = self._resolve_tool_handler(tn)
                if handler is None:
                    logger.warning("l3a subagent: tool %s handler not found", tn)
                    continue
                desc = tn
                params: dict[str, str] = {}
                try:
                    from l3.tool_system.tool_spec import get_tool as _gt
                    spec = _gt(tn)
                    if spec:
                        desc = spec.description or tn
                        if spec.parameters:
                            params = {p.name: p.type for p in spec.parameters}
                except Exception:
                    capture("l3a subagent: tool spec parse failed", error_code="E_L3A_SA", component="l3a", context={"tool_name": tn})
                    pass
                if tn == "cardwrite":
                    params = {"nature": "string", "title": "string",
                              "description": "string", "columns": "dict",
                              "priority": "int", "phases": "list"}
                    desc = "Create and submit a structured card."
                loop.add_tool(tn, desc, params, handler,
                              parallel_safe=(tn != "cardwrite"))
                registered.add(tn)

            model_cfg = self._resolve_model_config()
            result = loop.run(max_steps=max_steps, timeout=timeout,
                              model_config=model_cfg)
            answer = result.get("answer", "")
            findings = self._extract_findings(task_text, answer, spec)

            with self._lock:
                t = self._tasks.get(task_id)
                if t:
                    t.status = "done"
                    t.result = _pipeline.bound(findings)
                    t.completed_at = time.time()

            logger.debug("l3a subagent: %s done in %.1fs", task_id, time.time() - t0)
            return findings

        except Exception as e:
            capture("l3a subagent: run failed", error_code="E_L3A_SA", component="l3a", context={"task_id": task_id, "spec": spec_name})
            logger.warning("l3a subagent: %s failed: %s", task_id, e)
            with self._lock:
                t = self._tasks.get(task_id)
                if t:
                    t.status = "error"
                    t.result = {"error": str(e)}
                    t.completed_at = time.time()
            return {"error": str(e)}

    @staticmethod
    @staticmethod
    def _resolve_model_config() -> dict:
        try:
            from l3.services.model_service import get_service as _gs
            return _gs().resolve_dict("l3a_subagent")
        except Exception:
            capture("l3a subagent: model config resolve failed", error_code="E_L3A_SA", component="l3a")
            return {"max_tokens": _p.SA_DEFAULT_MAX_TOKENS, "temperature": _p.SA_DEFAULT_TEMPERATURE}

    @staticmethod
    def _extract_findings(task: str, answer: str,
                          spec: dict) -> dict:
        result: dict[str, Any] = {
            "task": task[:LOG_TRUNC_200],
            "summary": answer[:LOG_TRUNC_2000],
            "findings": [],
        }
        try:
            parsed = json.loads(answer)
            if isinstance(parsed, dict):
                result.update(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
        expect_keys = spec.get("expect_keys", [])
        for k in expect_keys:
            if k not in result:
                result[k] = []
        return result


# ── Global singleton ──

_pool: L3ASubAgentPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> L3ASubAgentPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = L3ASubAgentPool()
    return _pool


def reset_pool() -> None:
    global _pool
    if _pool:
        _pool.shutdown(wait=True)
    _pool = None


# ── Tool handlers (registered in L3A's AgentLoop) ──


def l3a_spawn_handler(args: dict, agent_id: str = "") -> dict:
    spec = args.get("spec", "investigator")
    task = args.get("task", "")
    group = args.get("group", "")
    expect = args.get("expect")
    return get_pool().commission(spec=spec, task=task, group=group, expect=expect)


def l3a_collect_handler(args: dict, agent_id: str = "") -> dict:
    group = args.get("group", "")
    timeout = float(args.get("timeout", 30))
    return get_pool().collect(group=group, timeout=timeout)


def l3a_peek_handler(args: dict, agent_id: str = "") -> dict:
    task_id = args.get("task_id", "")
    return get_pool().peek(task_id=task_id)
