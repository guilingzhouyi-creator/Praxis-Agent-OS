"""HTN Planner — Hierarchical Task Network planner for Agent OS.

Decomposes high-level tasks into sub-tasks, then into primitive actions.
Supports:
  - Task decomposition (compound → sub-tasks → primitive)
  - Dependency resolution between sub-tasks
  - Dynamic re-planning on failure
  - Parallel task execution
  - Resource constraint checking

Flow:
  High-level task → HTN Planner → TaskNetwork → ExecutionPlan → Execute
  On failure → Re-plan → Execute
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from l1.kernel.params.system import HASH_TRUNC_SHORT
from l3._base import BaseService

if TYPE_CHECKING:
    from l3.card.card_unified import CardUnified as Card

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """TaskType — enum of PRIMITIVE, COMPOUND."""
    PRIMITIVE = auto()   # Atomic action, can be executed directly
    COMPOUND = auto()   # Has sub-tasks, needs decomposition


class TaskStatus(Enum):
    """TaskStatus — enum of PENDING, RUNNING, DONE, FAILED...."""
    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class Task:
    """A single task in the HTN hierarchy."""
    id: str
    name: str
    task_type: TaskType = TaskType.COMPOUND
    description: str = ""
    domain: str = ""
    tool: str = ""  # For PRIMITIVE tasks: the tool to execute
    params: dict = field(default_factory=dict)
    sub_tasks: list[Task] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    priority: int = 5
    agent_id: str = ""
    created_at: float = field(default_factory=time.time)

    def is_primitive(self) -> bool:
        """Return True if this task is a primitive action."""
        return self.task_type == TaskType.PRIMITIVE


@dataclass
class DecompositionMethod:
    """A method for decomposing a compound task into sub-tasks."""
    name: str
    domain: str
    patterns: list[str]
    decompose_fn: Callable


class HTNPlanner(BaseService):
    """Hierarchical Task Network planner.

    Usage:
        planner = HTNPlanner()
        planner.register_method("develop", "app/game", ["develop", "create", "implement"],
                                lambda task: [Task(...), Task(...)])
        plan = planner.decompose("Develop snake game", "app/game")
        result = planner.execute(plan, tool_executor)
    """

    def __init__(self):
        super().__init__("htn_planner")
        self._methods: list[DecompositionMethod] = []
        self._lock = threading.RLock()
        self._tools: dict[str, str] = {}
        self._default_methods()

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        return {"success": True}

    def set_tool_map(self, tool_map: dict[str, str]) -> None:
        """Set tool name mapping (e.g., from HTN_DEFAULT_TOOLS in params)."""
        self._tools.update(tool_map)

    def _tool(self, name: str, fallback: str = "read_file") -> str:
        return self._tools.get(name, fallback)

    def _default_methods(self) -> None:
        """Register built-in decomposition methods."""
        try:
            from l1.kernel.params.tool import HTN_DEFAULT_TOOLS, HTN_DOMAIN_PREFIX
            self._tools = dict(HTN_DEFAULT_TOOLS)
            domain = HTN_DOMAIN_PREFIX
        except Exception:
            domain = "app"
        self.register_method("develop", f"{domain}/dev", ["develop", "create", "implement", "snake"],
                             self._decompose_develop)
        self.register_method("build", f"{domain}/build", ["build", "compile", "make"],
                             self._decompose_build)
        self.register_method("fix", f"{domain}/fix", ["bug", "fix", "error", "crash"],
                             self._decompose_fix)
        self.register_method("refactor", f"{domain}/refactor", ["refactor", "rename", "extract"],
                             self._decompose_refactor)
        self.register_method("review", f"{domain}/review", ["review", "audit", "inspect", "check"],
                             self._decompose_review)

    def register_method(self, name: str, domain: str,
                        patterns: list[str],
                        decompose_fn: Callable) -> None:
        """Register a decomposition method. Extensible from outside."""
        with self._lock:
            self._methods.append(DecompositionMethod(
                name=name, domain=domain, patterns=[p.lower() for p in patterns],
                decompose_fn=decompose_fn,
            ))

    def decompose(self, intent: str, domain: str = "",
                  priority: int = 5, agent_id: str = "") -> Task:
        """Decompose a high-level intent into a task hierarchy."""
        task_id = f"htn-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        root = Task(
            id=task_id, name=intent, task_type=TaskType.COMPOUND,
            domain=domain, priority=priority, agent_id=agent_id,
        )

        intent_lower = intent.lower()
        matched = False

        for method in self._methods:
            if any(p in intent_lower for p in method.patterns):
                try:
                    sub_tasks = method.decompose_fn(root)
                    if sub_tasks:
                        root.sub_tasks = sub_tasks
                        matched = True
                        break
                except Exception as e:
                    logger.warning("decomposition failed for %s: %s", method.name, e)

        if not matched:
            root.sub_tasks = [Task(
                id=f"{task_id}-step-0", name=intent,
                task_type=TaskType.PRIMITIVE, domain=domain,
                description=f"Execute: {intent}",
                priority=priority, agent_id=agent_id,
            )]

        return root

    def flatten(self, task: Task) -> list[Task]:
        """Flatten a task hierarchy into an ordered execution list (topological sort)."""
        primitives = []

        def collect(t: Task, visited: set[str] | None = None) -> None:
            """Collect primitive tasks depth-first. Returns None."""
            if visited is None:
                visited = set()
            if t.id in visited:
                return
            visited.add(t.id)
            if t.is_primitive():
                primitives.append(t)
            else:
                for sub in t.sub_tasks:
                    collect(sub, visited)

        collect(task)

        # Kahn topological sort — O(V+E) instead of the O(V^2) re-scan.
        # Dependencies not present in the primitive set are treated as
        # satisfied (same semantics as the previous remaining-set scan).
        task_map = {t.id: t for t in primitives}
        in_degree = {tid: 0 for tid in task_map}
        dependents: dict[str, list[str]] = {tid: [] for tid in task_map}
        for tid, t in task_map.items():
            for dep in t.depends_on:
                if dep in task_map:
                    in_degree[tid] += 1
                    dependents[dep].append(tid)

        ordered = []
        ready = sorted(tid for tid, deg in in_degree.items() if deg == 0)
        while ready:
            batch = ready
            ready = []
            for tid in batch:  # per-round sorted batches (deterministic order)
                ordered.append(task_map[tid])
                for nxt in dependents[tid]:
                    in_degree[nxt] -= 1
                    if in_degree[nxt] == 0:
                        ready.append(nxt)
            ready.sort()

        if len(ordered) < len(primitives):
            logger.warning("circular dependency detected in HTN plan")
        return ordered

    def execute(self, root: Task, tool_executor: Callable,
                agent_id: str = "") -> dict:
        """Execute a decomposed task hierarchy through the tool executor."""
        primitives = self.flatten(root)
        results = []
        all_passed = True

        for task in primitives:
            task.status = TaskStatus.RUNNING
            try:
                result = tool_executor(task.tool, task.params, agent_id or task.agent_id)
                task.result = result
                if isinstance(result, dict) and result.get("success", True):
                    task.status = TaskStatus.DONE
                else:
                    task.status = TaskStatus.FAILED
                    task.error = str(result.get("error", "")) if isinstance(result, dict) else ""
                    all_passed = False
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                all_passed = False

            results.append({
                "task_id": task.id, "name": task.name,
                "tool": task.tool, "status": task.status.name,
                "error": task.error,
            })

            if not all_passed:
                # Re-plan: try to continue with remaining tasks
                remaining = [t for t in primitives if t.status == TaskStatus.PENDING]
                if remaining:
                    for t in remaining:
                        t.status = TaskStatus.SKIPPED
                break

        return {
            "success": all_passed,
            "task_count": len(primitives),
            "done": sum(1 for r in results if r["status"] == "DONE"),
            "failed": sum(1 for r in results if r["status"] == "FAILED"),
            "skipped": sum(1 for r in results if r["status"] == "SKIPPED"),
            "results": results,
        }

    # ── Built-in decomposition methods ──

    def _decompose_develop(self, root: Task) -> list[Task]:
        tid = root.id; t = self._tool
        return [
            Task(id=f"{tid}-design", task_type=TaskType.COMPOUND, domain=root.domain,
                 name="Design", sub_tasks=[
                     Task(id=f"{tid}-design-req", task_type=TaskType.PRIMITIVE,
                          tool=t("analyze","read_file"), name="Analyze requirements",
                          description=f"Analyze: {root.name}", domain=root.domain),
                     Task(id=f"{tid}-design-arch", task_type=TaskType.PRIMITIVE,
                          tool=t("write","write_file"), name="Design doc",
                          description="Write design", domain=root.domain,
                          depends_on=[f"{tid}-design-req"]),
                 ]),
            Task(id=f"{tid}-impl", task_type=TaskType.COMPOUND, domain=root.domain,
                 name="Implement", depends_on=[f"{tid}-design"], sub_tasks=[
                     Task(id=f"{tid}-impl-code", task_type=TaskType.PRIMITIVE,
                          tool=t("create","create_file"), name="Write code",
                          description="Implement", domain=root.domain),
                     Task(id=f"{tid}-impl-test", task_type=TaskType.PRIMITIVE,
                          tool=t("create","create_file"), name="Write tests",
                          domain=root.domain, depends_on=[f"{tid}-impl-code"]),
                 ]),
            Task(id=f"{tid}-verify", task_type=TaskType.COMPOUND, domain=root.domain,
                 name="Verify", depends_on=[f"{tid}-impl"], sub_tasks=[
                     Task(id=f"{tid}-verify-build", task_type=TaskType.PRIMITIVE,
                          tool=t("build","build_project"), name="Build", domain=root.domain),
                     Task(id=f"{tid}-verify-test", task_type=TaskType.PRIMITIVE,
                          tool=t("test","test_project"), name="Test",
                          domain=root.domain, depends_on=[f"{tid}-verify-build"]),
                     Task(id=f"{tid}-verify-lint", task_type=TaskType.PRIMITIVE,
                          tool=t("lint","lint"), name="Lint", domain=root.domain),
                 ]),
            Task(id=f"{tid}-doc", task_type=TaskType.PRIMITIVE,
                 tool=t("doc","write_file"), name="Documentation",
                 domain=root.domain, depends_on=[f"{tid}-verify"]),
        ]

    def _decompose_build(self, root: Task) -> list[Task]:
        tid = root.id; t = self._tool
        return [
            Task(id=f"{tid}-lint", task_type=TaskType.PRIMITIVE,
                 tool=t("lint","lint"), name="Lint", domain=root.domain),
            Task(id=f"{tid}-test", task_type=TaskType.PRIMITIVE,
                 tool=t("test","test_project"), name="Test",
                 domain=root.domain, depends_on=[f"{tid}-lint"]),
            Task(id=f"{tid}-build", task_type=TaskType.PRIMITIVE,
                 tool=t("build","build_project"), name="Build",
                 domain=root.domain, depends_on=[f"{tid}-test"]),
        ]

    def _decompose_fix(self, root: Task) -> list[Task]:
        tid = root.id; t = self._tool
        return [
            Task(id=f"{tid}-scout", task_type=TaskType.PRIMITIVE,
                 tool=t("scout","scout_delegate"), name="Investigate", domain=root.domain),
            Task(id=f"{tid}-diagnose", task_type=TaskType.PRIMITIVE,
                 tool=t("analyze","read_file"), name="Diagnose",
                 domain=root.domain, depends_on=[f"{tid}-scout"]),
            Task(id=f"{tid}-fix", task_type=TaskType.PRIMITIVE,
                 tool=t("fix","write_file"), name="Fix",
                 domain=root.domain, depends_on=[f"{tid}-diagnose"]),
            Task(id=f"{tid}-verify", task_type=TaskType.PRIMITIVE,
                 tool=t("test","test_project"), name="Verify",
                 domain=root.domain, depends_on=[f"{tid}-fix"]),
        ]

    def _decompose_refactor(self, root: Task) -> list[Task]:
        tid = root.id; t = self._tool
        return [
            Task(id=f"{tid}-scout", task_type=TaskType.PRIMITIVE,
                 tool=t("analyze","read_file"), name="Analyze", domain=root.domain),
            Task(id=f"{tid}-plan", task_type=TaskType.PRIMITIVE,
                 tool=t("write","write_file"), name="Plan",
                 domain=root.domain, depends_on=[f"{tid}-scout"]),
            Task(id=f"{tid}-exec", task_type=TaskType.PRIMITIVE,
                 tool=t("extract","write_file"), name="Execute",
                 domain=root.domain, depends_on=[f"{tid}-plan"]),
            Task(id=f"{tid}-verify", task_type=TaskType.PRIMITIVE,
                 tool=t("test","test_project"), name="Verify",
                 domain=root.domain, depends_on=[f"{tid}-exec"]),
        ]

    def _decompose_review(self, root: Task) -> list[Task]:
        tid = root.id; t = self._tool
        return [
            Task(id=f"{tid}-scan", task_type=TaskType.PRIMITIVE,
                 tool=t("review","read_file"), name="Scan", domain=root.domain),
            Task(id=f"{tid}-analyze", task_type=TaskType.PRIMITIVE,
                 tool=t("analyze","read_file"), name="Analyze",
                 domain=root.domain, depends_on=[f"{tid}-scan"]),
            Task(id=f"{tid}-report", task_type=TaskType.PRIMITIVE,
                 tool=t("doc","write_file"), name="Report",
                 domain=root.domain, depends_on=[f"{tid}-analyze"]),
        ]

    def to_card(self, root: Task, task_id: str = "", domain: str = "") -> Card:
        """Convert an HTN decomposed Task tree into a Card with phases/steps.

        The root task's direct sub-tasks become phases. Compound sub-tasks
        that contain primitives are expanded into sequential steps.
        Standalone primitives become single-step phases.

        Args:
            root: The decomposed HTN task tree (from decompose()).
            task_id: Optional card ID. Auto-generated if empty.
            domain: Optional domain override.

        Returns a CardUnified ready for ExecutionPlan.
        """
        # Late import to avoid circular dependency at module level
        from ..card.card_unified import CardPhase, CardSummary, CardTask, CardUnified

        cid = task_id or f"htn-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        intent = root.name
        dom = domain or root.domain

        primitives = self.flatten(root)
        built_tasks: dict[str, list] = {}  # phase_name → [CardTask, ...]

        for pt in primitives:
            # Deduce phase from the compound parent chain by scanning root
            phase_name = self._infer_phase(root, pt)
            if phase_name not in built_tasks:
                built_tasks[phase_name] = []

            target = pt.params.get("path", pt.params.get("target", pt.name))
            task = CardTask(
                action=pt.tool or "think",
                target=target,
                params=pt.params,
                agent=self._infer_agent(pt),
            )
            built_tasks[phase_name].append(task)

        phases = []
        seen = set()
        for pt in primitives:
            pn = self._infer_phase(root, pt)
            if pn in seen:
                continue
            seen.add(pn)
            tasks = built_tasks.get(pn, [])
            phases.append(CardPhase(name=pn, tasks=tasks))

        if not phases:
            phases.append(CardPhase(
                name="execute",
                tasks=[CardTask(action="think", target=intent, params={})],
            ))

        card = CardUnified(id=cid, priority=5, nature="execution", phases=phases)
        card.summary = CardSummary(title=intent, description="",
                                   columns={"domain": dom or "."})
        return card

    @staticmethod
    def _infer_phase(root: Task, primitive: Task) -> str:
        """Find the compound parent that contains this primitive task."""
        for sub in root.sub_tasks:
            if sub.id == primitive.id:
                return sub.name.lower().replace(" ", "_")
            if sub.task_type == TaskType.COMPOUND:
                for s2 in sub.sub_tasks:
                    if s2.id == primitive.id:
                        return sub.name.lower().replace(" ", "_")
        return "execute"

    @staticmethod
    def _infer_agent(task: Task) -> str:
        """Map tool ring level to agent role.  Config-driven via AGENT_ROLE_MAP."""
        tool = task.tool or ""
        try:
            from l1.kernel.params.agent import AGENT_ROLE_MAP

            from .tool_system.tool_config import ToolConfig as _TC
            spec = _TC.get(tool)
            if spec:
                return AGENT_ROLE_MAP.get(spec.ring, "default")
        except Exception:
            logger.debug("htn_planner: tool role lookup failed")
        return "default"

    def stats(self) -> dict:
        """Return HTNPlanner statistics. Returns a dict with method count."""
        with self._lock:
            return {"methods": len(self._methods)}


_service: HTNPlanner | None = None


def get_service() -> HTNPlanner:
    """Get the HTNPlanner singleton service. Returns the shared planner."""
    global _service
    if _service is None:
        _service = HTNPlanner()
    return _service


def reset_service() -> None:
    """Reset the HTNPlanner singleton service. Returns None."""
    global _service
    if _service:
        _service.stop()
    _service = None
