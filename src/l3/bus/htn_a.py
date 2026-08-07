"""HTN-A — Global-level card shard service.

In the triple-HTN architecture responsible for "star distribution":
  HTN-A receives user intent → decomposes into cross-Cell subtask trees
  → each subtask is tagged with agent_id="cell-N"
  → CentralController then distributes the card shards to the corresponding L3B+HTN-B complexes

Architecture position (above all Cells):
  HTN-A          ← Central decomposition
   │
   ├─ L3B+B[1↔2] → Cell-1
   ├─ L3B+B[2↔3] → Cell-2
   └─ L3B+B[3↔4] → Cell-3

Relationship with HTN-B/C:
  HTN-A : "What tasks need to cross Cells?" (high-level intent decomposition)
  HTN-B : "How should this subtask be routed to the next Cell?" (cross-Cell routing decomposition)
  HTN-C : "How should this subtask be broken down inside a Cell?" (intra-Cell execution decomposition)

All share the same HTNPlanner class, only the registered methods differ.
"""

from __future__ import annotations

import logging

from l1.kernel.params.agent import DEFAULT_CELL_ID

from .htn_planner import HTNPlanner, Task, TaskType

logger = logging.getLogger(__name__)

# ── HTN-A Instance ──────────────────────────────────────────────────

_htn_a: HTNPlanner | None = None


def get_htn_a() -> HTNPlanner:
    """Get the HTN-A global singleton."""
    global _htn_a
    if _htn_a is None:
        _htn_a = _create_htn_a()
    return _htn_a


def reset_htn_a() -> None:
    """Reset the HTN-A singleton. Returns None."""
    global _htn_a
    _htn_a = None


def _create_htn_a() -> HTNPlanner:
    """Create an HTN-A instance and register cross-Cell decomposition methods."""
    planner = HTNPlanner()
    planner.name = "htn_a"

    # Clear default HTN-C methods (HTN-A only registers pipeline methods)
    planner._methods.clear()

    # ── Cross-Cell Pipeline Decomposition Methods ──

    planner.register_method(
        "pipeline_full",
        "app/dev",
        ["develop", "create", "implement", "build"],
        _decompose_pipeline_dev,
    )

    planner.register_method(
        "pipeline_fix",
        "app/fix",
        ["bug", "fix", "error", "crash", "repair"],
        _decompose_pipeline_fix,
    )

    planner.register_method(
        "pipeline_review",
        "app/review",
        ["review", "audit", "inspect", "check"],
        _decompose_pipeline_review,
    )

    logger.info("HTN-A created with %d methods", len(planner._methods))
    return planner


# ── Cross-Cell Decomposition Methods ────────────────────────────────

# Cell order is determined by CentralController at registration time; here we tag according to the cell-1/cell-2/cell-3 convention.


def _decompose_pipeline_dev(root: Task) -> list[Task]:
    """Develop workflow: design(cell-1) → implement(cell-2) → review(cell-3)"""
    tid = root.id
    return [
        Task(
            id=f"{tid}-design",
            name="Design",
            task_type=TaskType.COMPOUND,
            domain=root.domain,
            agent_id="cell-1",
            sub_tasks=[
                Task(id=f"{tid}-design-req", name="Analyze requirements",
                     task_type=TaskType.PRIMITIVE, tool="read_file",
                     domain=root.domain, agent_id="cell-1"),
                Task(id=f"{tid}-design-doc", name="Write design doc",
                     task_type=TaskType.PRIMITIVE, tool="write_file",
                     domain=root.domain, agent_id="cell-1",
                     depends_on=[f"{tid}-design-req"]),
            ],
        ),
        Task(
            id=f"{tid}-impl",
            name="Implement",
            task_type=TaskType.COMPOUND,
            domain=root.domain,
            agent_id="cell-2",
            depends_on=[f"{tid}-design"],
            sub_tasks=[
                Task(id=f"{tid}-impl-code", name="Write code",
                     task_type=TaskType.PRIMITIVE, tool="create_file",
                     domain=root.domain, agent_id="cell-2"),
                Task(id=f"{tid}-impl-test", name="Write tests",
                     task_type=TaskType.PRIMITIVE, tool="create_file",
                     domain=root.domain, agent_id="cell-2",
                     depends_on=[f"{tid}-impl-code"]),
            ],
        ),
        Task(
            id=f"{tid}-verify",
            name="Verify",
            task_type=TaskType.COMPOUND,
            domain=root.domain,
            agent_id="cell-3",
            depends_on=[f"{tid}-impl"],
            sub_tasks=[
                Task(id=f"{tid}-verify-build", name="Build",
                     task_type=TaskType.PRIMITIVE, tool="build_project",
                     domain=root.domain, agent_id="cell-3"),
                Task(id=f"{tid}-verify-test", name="Test",
                     task_type=TaskType.PRIMITIVE, tool="test_project",
                     domain=root.domain, agent_id="cell-3",
                     depends_on=[f"{tid}-verify-build"]),
            ],
        ),
    ]


def _decompose_pipeline_fix(root: Task) -> list[Task]:
    """Fix workflow: diagnose(cell-1) → fix(cell-2) → verify(cell-3)"""
    tid = root.id
    return [
        Task(
            id=f"{tid}-diagnose",
            name="Diagnose",
            task_type=TaskType.PRIMITIVE,
            tool="scout_delegate",
            domain=root.domain,
            agent_id="cell-1",
        ),
        Task(
            id=f"{tid}-fix",
            name="Fix",
            task_type=TaskType.PRIMITIVE,
            tool="write_file",
            domain=root.domain,
            agent_id="cell-2",
            depends_on=[f"{tid}-diagnose"],
        ),
        Task(
            id=f"{tid}-verify",
            name="Verify",
            task_type=TaskType.PRIMITIVE,
            tool="test_project",
            domain=root.domain,
            agent_id="cell-3",
            depends_on=[f"{tid}-fix"],
        ),
    ]


def _decompose_pipeline_review(root: Task) -> list[Task]:
    """Review workflow: scan(cell-1) → analyze(cell-2) → report(cell-3)"""
    tid = root.id
    return [
        Task(
            id=f"{tid}-scan",
            name="Scan",
            task_type=TaskType.PRIMITIVE,
            tool="read_file",
            domain=root.domain,
            agent_id="cell-1",
        ),
        Task(
            id=f"{tid}-analyze",
            name="Analyze",
            task_type=TaskType.PRIMITIVE,
            tool="analyze",
            domain=root.domain,
            agent_id="cell-2",
            depends_on=[f"{tid}-scan"],
        ),
        Task(
            id=f"{tid}-report",
            name="Report",
            task_type=TaskType.PRIMITIVE,
            tool="write_file",
            domain=root.domain,
            agent_id="cell-3",
            depends_on=[f"{tid}-analyze"],
        ),
    ]


def get_shards(root: Task) -> list[dict]:
    """Flatten the HTN-A Task tree and group by cell_id into shards.

    Returns:
      [{"cell_id": "cell-1", "tasks": [Task, ...]},
       {"cell_id": "cell-2", "tasks": [Task, ...]}, ...]
    """
    planner = get_htn_a()
    primitives = planner.flatten(root)
    shards: dict[str, list[Task]] = {}
    for pt in primitives:
        cid = pt.agent_id or DEFAULT_CELL_ID
        shards.setdefault(cid, []).append(pt)
    return [
        {"cell_id": cid, "tasks": tasks}
        for cid, tasks in shards.items()
    ]
