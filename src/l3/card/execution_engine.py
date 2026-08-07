"""ExecutionEngine — execution plan, step dependencies, retry/rollback, persistent.

The layer between HTN Planner (abstract task decomposition) and Tool Executor (gate + run).
Takes a structured ExecutionPlan, executes steps in dependency order,
handles failures with retry/skip/rollback strategies.

Persistence: Execution results saved to JSON file at get_paths().execution_results.

Flow:
  ExecutionPlan → topological sort → execute each step → collect results
  On failure: retry (N times) → skip (continue) → rollback (undo)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.params.system import (
    EXEC_BACKOFF_INTERVAL,
    EXECUTION_RESULT_RETENTION,
    EXECUTION_RESULTS_AUTO_SAVE,
    EXECUTION_STEP_TIMEOUT,
)
from l1.kernel.paths import get_paths as _gp
from l3._base import BaseService
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)

# ── Rollback handler registry ──
# External code can register custom rollback handlers via register_rollback().
_rollback_handlers: dict[str, Callable] = {}


def register_rollback(tool_name: str, handler: Callable) -> None:
    """Register a rollback handler for a tool name.

    The handler receives (step: Step, plan: ExecutionPlan, executor: Callable).
    It should undo the effect of the tool using the step.params.
    """
    _rollback_handlers[tool_name] = handler


def _get_rollback_handler(tool_name: str) -> Callable | None:
    return _rollback_handlers.get(tool_name)


def _register_default_rollbacks() -> None:
    """Register built-in rollback handlers for common file tools."""

    def _rollback_replace(s, plan, executor):
        params = s.params
        if "old_string" in params and "new_string" in params:
            executor(
                "replace_string_in_file",
                {
                    "path": params.get("path", ""),
                    "old_string": params["new_string"],
                    "new_string": params["old_string"],
                },
                plan.agent_id,
            )

    def _rollback_file_create(s, plan, executor):
        path = s.params.get("path", "")
        if path:
            import os as _os

            if _os.path.exists(path):
                _os.remove(path)

    def _rollback_rename(s, plan, executor):
        old_path = s.params.get("old", "") or s.params.get("old_path", "")
        new_path = s.params.get("new", "") or s.params.get("new_path", "")
        if old_path and new_path:
            import shutil as _su

            _su.move(new_path, old_path)

    register_rollback("replace_string_in_file", _rollback_replace)
    for t in ("write_file", "create_file", "create"):
        register_rollback(t, _rollback_file_create)
    register_rollback("rename", _rollback_rename)


_register_default_rollbacks()


class StepStatus(Enum):
    """StepStatus — enum of PENDING, RUNNING, DONE, FAILED...."""

    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()
    SKIPPED = auto()
    ROLLED_BACK = auto()


class RecoveryStrategy(Enum):
    """RecoveryStrategy — enum of ABORT, RETRY, SKIP, ROLLBACK."""

    ABORT = "abort"  # Stop execution, mark failed
    RETRY = "retry"  # Retry N times
    SKIP = "skip"  # Skip this step, continue
    ROLLBACK = "rollback"  # Run rollback steps, then abort


@dataclass
class Step:
    """A single execution step."""

    id: str
    tool: str
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    timeout: float = EXECUTION_STEP_TIMEOUT
    retry_count: int = 0
    max_retries: int = 2
    recovery: str = RecoveryStrategy.ABORT.value
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    elapsed: float = 0.0


@dataclass
class ExecutionPlan:
    """Execution plan — ordered steps with context."""

    plan_id: str
    intent: str
    agent_id: str
    steps: list[Step] = field(default_factory=list)
    context_refs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add_step(
        self,
        tool: str,
        params: dict | None = None,
        depends_on: list[str] | None = None,
        recovery: str = RecoveryStrategy.ABORT.value,
        max_retries: int = 2,
    ) -> Step:
        """Append a step to the plan and return the created Step."""
        step = Step(
            id=f"step-{len(self.steps)}",
            tool=tool,
            params=params or {},
            depends_on=depends_on or [],
            recovery=recovery,
            max_retries=max_retries,
        )
        self.steps.append(step)
        return step


@dataclass
class ExecutionResult:
    """Execution result — summary of all steps."""

    plan_id: str
    success: bool
    steps: list[dict] = field(default_factory=list)
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    elapsed: float = 0.0
    error: str = ""


class ExecutionEngine(BaseService, PersistableMixin):
    """Execution engine — plans, steps, dependencies, recovery, results persisted.

    Usage:
        engine = ExecutionEngine()
        plan = ExecutionPlan(plan_id="p-001", intent="modify config", agent_id="agent_b")
        plan.add_step("read_file", {"path": "config.py"})
        plan.add_step("replace_string", {"old": "localhost", "new": "production"},
                      depends_on=["step-0"], recovery="retry")
        result = engine.execute(plan, tool_executor=my_executor)
    """

    persistence_kind = "execution_result"

    def __init__(self, persist_path: str = ""):
        super().__init__("execution_engine")
        self._executions: OrderedDict[str, ExecutionResult] = OrderedDict()
        self._lock = threading.RLock()
        self._init_persistence(persist_path or _gp().execution_results, EXECUTION_RESULTS_AUTO_SAVE)
        self._restore()
        if EXECUTION_RESULTS_AUTO_SAVE > 0:
            self._start_auto_save()

    def _serialize(self) -> dict:
        def _result_dict(r: ExecutionResult) -> dict:
            return {
                "plan_id": r.plan_id,
                "success": r.success,
                "steps": r.steps,
                "total": r.total,
                "done": r.done,
                "failed": r.failed,
                "skipped": r.skipped,
                "elapsed": r.elapsed,
                "error": r.error,
            }

        return {"executions": {pid: _result_dict(r) for pid, r in self._executions.items()}}

    def _deserialize(self, data: dict) -> bool:
        self._executions.clear()
        for pid, d in data.get("executions", {}).items():
            self._executions[pid] = ExecutionResult(
                plan_id=d["plan_id"],
                success=d.get("success", True),
                steps=d.get("steps", []),
                total=d.get("total", 0),
                done=d.get("done", 0),
                failed=d.get("failed", 0),
                skipped=d.get("skipped", 0),
                elapsed=d.get("elapsed", 0.0),
                error=d.get("error", ""),
            )
        return True

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        self._persist()
        with self._lock:
            self._executions.clear()
        return {"success": True}

    def execute(self, plan: ExecutionPlan, tool_executor: Callable | None = None) -> ExecutionResult:
        """Execute a plan: topological sort → run steps → collect results."""
        if tool_executor is None:

            def _default_executor(tool: str, params: dict, agent_id: str) -> dict:
                from l3.tool_system.tool_pipeline import get_pipeline

                return get_pipeline().execute(tool_name=tool, agent_id=agent_id, args=params)

            tool_executor = _default_executor
        started_at = time.time()
        result = ExecutionResult(plan_id=plan.plan_id, success=True, total=len(plan.steps))

        # 1. Topological sort
        order = self._topological_sort(plan.steps)
        if order is None:
            result.success = False
            result.error = "circular dependency detected"
            with self._lock:
                self._executions[plan.plan_id] = result
                self._trim_executions_locked()
            return result

        # 2. Execute steps in order
        step_map = {s.id: s for s in plan.steps}
        for step in order:
            if step.status == StepStatus.SKIPPED:
                result.skipped += 1
                continue

            step.status = StepStatus.RUNNING
            step.started_at = time.time()

            # Check dependencies
            deps_met = self._check_dependencies(step, step_map)
            if not deps_met:
                step.status = StepStatus.SKIPPED
                step.error = "dependency not met"
                result.skipped += 1
                continue

            # Execute with retry
            success = self._execute_with_retry(step, plan.agent_id, tool_executor)

            if success:
                step.status = StepStatus.DONE
                step.completed_at = time.time()
                step.elapsed = step.completed_at - step.started_at
                result.done += 1
            else:
                step.status = StepStatus.FAILED
                step.completed_at = time.time()
                step.elapsed = step.completed_at - step.started_at
                result.failed += 1

                # Recovery strategy
                handler = getattr(self, f"_recovery_{step.recovery}", self._recovery_abort)
                r = handler(step, plan, tool_executor)
                if r.get("abort", False):
                    result.success = False
                    result.error = f"step {step.id} failed: {step.error}"
                    break

        result.elapsed = time.time() - started_at
        result.steps = [
            {"id": s.id, "tool": s.tool, "status": s.status.name, "error": s.error, "elapsed": round(s.elapsed, 3)}
            for s in plan.steps
        ]

        with self._lock:
            self._executions[plan.plan_id] = result
            self._trim_executions_locked()
        logger.info("execution %s: %d/%d done, %.2fs", plan.plan_id, result.done, result.total, result.elapsed)
        return result

    def _trim_executions_locked(self) -> None:
        """Drop oldest results beyond the retention cap (bounded memory)."""
        while len(self._executions) > EXECUTION_RESULT_RETENTION:
            self._executions.popitem(last=False)

    def _execute_with_retry(self, step: Step, agent_id: str, executor: Callable) -> bool:
        """Execute a step with retry logic."""
        for attempt in range(step.max_retries + 1):
            try:
                step.result = executor(step.tool, step.params, agent_id)
                if isinstance(step.result, dict) and step.result.get("success", True):
                    return True
                step.error = str(step.result.get("error", "")) if isinstance(step.result, dict) else ""
            except Exception as e:
                step.error = str(e)

            if attempt < step.max_retries:
                logger.warning("step %s retry %d/%d: %s", step.id, attempt + 1, step.max_retries, step.error)
                time.sleep(EXEC_BACKOFF_INTERVAL)  # Backoff
            step.retry_count = attempt + 1

        return False

    def _check_dependencies(self, step: Step, step_map: dict[str, Step]) -> bool:
        """Check if all dependencies are met (step_map built once by the caller)."""
        for dep_id in step.depends_on:
            dep = step_map.get(dep_id)
            if not dep or dep.status != StepStatus.DONE:
                return False
        return True

    def _topological_sort(self, steps: list[Step]) -> list[Step] | None:
        """Topological sort by dependency. Returns None if circular."""
        step_map = {s.id: s for s in steps}
        visited = set()  # permanently visited (done)
        in_stack = set()  # in current DFS path (cycle detection)
        result = []

        def dfs(sid: str) -> bool:
            """Visit a step recursively; returns False on cycle."""
            if sid in in_stack:
                return False  # cycle detected
            if sid in visited:
                return True  # already processed
            in_stack.add(sid)
            step = step_map.get(sid)
            if step:
                for dep_id in step.depends_on:
                    if dep_id in step_map and not dfs(dep_id):
                        return False
                result.append(step)
            in_stack.discard(sid)
            visited.add(sid)
            return True

        for step in steps:
            if not dfs(step.id):
                return None
        return result

    # ── Recovery strategies ──

    def _recovery_abort(self, step: Step, plan: ExecutionPlan, executor: Callable) -> dict:
        return {"abort": True}

    def _recovery_retry(self, step: Step, plan: ExecutionPlan, executor: Callable) -> dict:
        return {"abort": True}

    def _recovery_skip(self, step: Step, plan: ExecutionPlan, executor: Callable) -> dict:
        step.status = StepStatus.SKIPPED
        return {"abort": False}

    def _recovery_rollback(self, step: Step, plan: ExecutionPlan, executor: Callable) -> dict:
        for s in reversed(plan.steps):
            if s.status != StepStatus.DONE:
                continue
            try:
                fn = _get_rollback_handler(s.tool)
                if fn:
                    fn(s, plan, executor)
                s.status = StepStatus.ROLLED_BACK
            except Exception as e:
                logger.warning("execution_engine rollback: %s", e)
        return {"abort": True}

    def get_result(self, plan_id: str) -> dict | None:
        """Return the result for a plan, or None if not found."""
        with self._lock:
            r = self._executions.get(plan_id)
            if not r:
                return None
            return {
                "plan_id": r.plan_id,
                "success": r.success,
                "total": r.total,
                "done": r.done,
                "failed": r.failed,
                "skipped": r.skipped,
                "elapsed": round(r.elapsed, 3),
                "error": r.error,
                "steps": r.steps,
            }

    def stats(self) -> dict:
        """Return execution counts and plan IDs."""
        with self._lock:
            return {"executions": len(self._executions), "plans": list(self._executions.keys())}


_service: ExecutionEngine | None = None


def get_service() -> ExecutionEngine:
    """Return the ExecutionEngine singleton, creating it if needed."""
    global _service
    if _service is None:
        _service = ExecutionEngine()
    return _service


def reset_service() -> None:
    """Stop and reset the ExecutionEngine singleton."""
    global _service
    if _service:
        _service.stop()
    _service = None
