"""SubAgentGate — card type gate for SubAgentPool dispatch classification.

Each card dispatched to the SubAgent pool passes through this gate,
which classifies it by intent/action:

  ExploreCard — read-only investigation (Ring 1 tools only)
    → routes to the explore buffer in SubAgentPool
    → spec.read_only=True

  ExecuteCard — read-write multi-step execution (Ring 2 / 2.5 tools)
    → routes to the execute buffer in SubAgentPool
    → spec.read_only=False

Gate logic:
  - Inspects the card's phases / tasks / agent / target
  - If any task has a write tool (write_file, edit, delete, …) → ExecuteCard
  - If all tasks are read-only (read_file, grep, search, …) → ExploreCard
"""

from __future__ import annotations

from typing import Any

from .subagent_spec import SubAgentSpec

# Well-known write tool names — if any task uses one, the card is "execute"
_WRITE_TOOLS: frozenset[str] = frozenset({
    "write_file", "edit", "edit_file", "delete", "delete_file",
    "create", "mkdir", "rename", "move", "copy",
    "run", "terminal", "execute", "build", "install",
})


def classify_card(card: Any) -> str:
    """Classify a card as 'explore' or 'execute' by inspecting its phases/tasks.

    Returns: 'explore' — read-only tasks only
             'execute' — at least one write/run task
    """
    phases = getattr(card, "phases", []) or []
    for phase in phases:
        tasks = getattr(phase, "tasks", getattr(phase, "steps", [])) or []
        for task in tasks:
            action = getattr(task, "action", "") or (isinstance(task, dict) and task.get("action", ""))
            if action in _WRITE_TOOLS:
                return "execute"
            # Check agent role — "writer" roles imply write work
            agent = getattr(task, "agent", "") or (isinstance(task, dict) and task.get("agent", ""))
            if agent in ("writer", "developer", "builder"):
                return "execute"
    return "explore"


def build_spec(card_type: str, spec_name: str = "") -> SubAgentSpec:
    """Build a SubAgentSpec from the card type classification.

    ExploreCard → read_only=True,  Ring 1
    ExecuteCard → read_only=False, Ring 2
    """
    if card_type == "execute":
        return SubAgentSpec(
            name=spec_name or "execute-assistant",
            description="Multi-step execution assistant (Ring 2)",
            read_only=False,
            max_steps=10,
        )
    return SubAgentSpec(
        name=spec_name or "explore-assistant",
        description="Read-only investigation assistant (Ring 1)",
        read_only=True,
        max_steps=5,
    )
