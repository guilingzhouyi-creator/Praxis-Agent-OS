"""HTN-B — Cross-Cell Routing Decomposition.

Mounted inside each L3B composite in the triple HTN architecture:
  HTN-A: "What tasks need to cross cells?"           → Top-level intent decomposition
  HTN-B: "How does this subtask route to the next?" → Cross-cell routing decomposition
  HTN-C: "How is the subtask decomposed inside the cell?" → Intra-cell execution decomposition

HTN-B constraints:
  - Can only read the previous cell's L2 cache summary (cannot read successor cells)
  - Can only dispatch to the next adjacent cell (no multi-hop)
  - Count = max(0, Cell_count - 1), auto-created as cells are registered
"""

from __future__ import annotations

import logging
from typing import Any

from .htn_planner import HTNPlanner, Task, TaskType

logger = logging.getLogger(__name__)


def create_htn_b(prev_cell_id: str, next_cell_id: str) -> HTNPlanner:
    """Create an HTN-B instance, registering routing decomposition methods between two cells.

    Args:
        prev_cell_id: Previous cell ID (read-only access to its L2 cache)
        next_cell_id: Successor cell ID (dispatch target)
    """
    planner = HTNPlanner()
    planner.name = f"htn_b_{prev_cell_id}_{next_cell_id}"

    # Register cross-cell routing methods
    planner.register_method(
        "route_forward",
        "app/route",
        ["route", "forward", "dispatch", "next"],
        lambda root: _decompose_route_forward(root, prev_cell_id, next_cell_id),
    )

    planner.register_method(
        "merge_back",
        "app/merge",
        ["merge", "collect", "aggregate", "result"],
        lambda root: _decompose_merge_result(root, prev_cell_id, next_cell_id),
    )

    logger.info(
        "HTN-B created for %s → %s (%d methods)",
        prev_cell_id, next_cell_id, len(planner._methods),
    )
    return planner


def _decompose_route_forward(
    root: Task, prev_cell: str, next_cell: str,
) -> list[Task]:
    """Decompose an HTN-A subtask into an execution plan for "routing to the next cell".

    Steps:
      1. Read the previous cell's L2 cache summary (check whether prerequisite work is complete)
      2. Encapsulate the task as a dispatchable card for the next station
      3. Mark target_cell = next_cell
    """
    tid = root.id
    return [
        Task(
            id=f"{tid}-check-prev",
            name=f"Check {prev_cell} L2 cache",
            task_type=TaskType.PRIMITIVE,
            tool="cache_search",
            domain=root.domain,
            agent_id=prev_cell,
            params={
                "action": "read_summary",
                "prev_cell": prev_cell,
                "query": root.name,
            },
        ),
        Task(
            id=f"{tid}-route",
            name=f"Route to {next_cell}",
            task_type=TaskType.PRIMITIVE,
            tool="dispatch_to_next",
            domain=root.domain,
            agent_id=next_cell,
            params={
                "action": "dispatch_card",
                "target_cell": next_cell,
                "task_name": root.name,
                "depends_on": [f"{tid}-check-prev"],
            },
        ),
    ]


def _decompose_merge_result(
    root: Task, prev_cell: str, next_cell: str,
) -> list[Task]:
    """Aggregate the result returned by the successor cell and prepare it for the next composite or HTN-A."""
    tid = root.id
    return [
        Task(
            id=f"{tid}-collect",
            name=f"Collect result from {next_cell}",
            task_type=TaskType.PRIMITIVE,
            tool="collect_result",
            domain=root.domain,
            agent_id=next_cell,
            params={"action": "collect", "source_cell": next_cell},
        ),
        Task(
            id=f"{tid}-summarize",
            name="Summarize result",
            task_type=TaskType.PRIMITIVE,
            tool="summarize",
            domain=root.domain,
            agent_id=prev_cell,
            params={"action": "summarize", "input_from": next_cell},
        ),
    ]


def route_from_htn_a(
    htn_b: HTNPlanner,
    subtask: Task,
    prev_summary: str,
    next_cell: str,
) -> list[Task]:
    """HTN-B entry point: receives an HTN-A subtask + previous cell summary,
    and decomposes it into an execution plan routable to the next cell.

    Args:
        htn_b: HTN-B planner instance
        subtask: Subtask produced by HTN-A
        prev_summary: Previous cell's L2 cache summary text
        next_cell: Target cell ID

    Returns:
        List of decomposed primitive tasks
    """
    # Build a compound task that includes the previous summary context
    route_task = Task(
        id=f"route-{subtask.id}",
        name=subtask.name,
        task_type=TaskType.COMPOUND,
        domain=subtask.domain,
        agent_id=next_cell,
        description=f"Route: {subtask.name} → {next_cell} | Prev summary: {prev_summary[:200]}",
    )
    decomposed = htn_b.decompose(f"route {subtask.name} to {next_cell}", subtask.domain)
    return decomposed.sub_tasks if decomposed.sub_tasks else []
