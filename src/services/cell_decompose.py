"""Card decomposition engine — extracted from cell.py for modularity.

Decomposes a Card by territory into sub-cards routed to specific agents.
"""

from __future__ import annotations

from typing import Any

from kernel.params import TERRITORY_MAP, TERRITORY_PATHS


def decompose_card(domain: str, card: Any, cell_id: str, ensure_terminal_fn=None) -> list[dict]:
    """Split a Card into territory-scoped sub-cards.

    Args:
        domain: project domain/path prefix for territory matching.
        card: the structured Card with phases and steps.
        cell_id: used to generate agent IDs like f"{cell_id}-{role}".
        ensure_terminal_fn: callable(aid, role, territory) to boot terminals.

    Returns:
        list of {"card": Card, "role": str, "agent_id": str,
                 "agent_map": dict, "territory": list[str]}
    """
    from .card import Card, Phase, PhaseMode

    domain = domain or card.domain
    slices: list[dict] = []
    seen_roles: set[str] = set()

    for prefix, role in TERRITORY_MAP.items():
        if domain and not (domain.startswith(prefix) or prefix.startswith(domain)):
            continue
        if role in seen_roles:
            continue
        seen_roles.add(role)
        aid = f"{cell_id}-{role}"
        terr = [prefix]

        steps_for_role = []
        for phase in card.phases:
            for step in phase.steps:
                if step.agent == role or step.agent == "scout":
                    steps_for_role.append(step)

        sub_phases = []
        if steps_for_role:
            sub_phases.append(Phase(name=f"{role}_work", mode=PhaseMode.PARALLEL,
                                     steps=steps_for_role))

        sub_card = Card(id=f"{card.id}-{role}", intent=card.intent,
                        domain=prefix, mode=card.mode, priority=card.priority,
                        phases=sub_phases)
        result = {"card": sub_card, "role": role, "agent_id": aid,
                  "agent_map": {role: aid, "scout": "scout_pool"},
                  "territory": terr}
        slices.append(result)

        if ensure_terminal_fn:
            ensure_terminal_fn(aid, role, terr)

    return slices


def auto_agent_map(card: Any, cell_id: str, ensure_terminal_fn=None) -> dict[str, str]:
    """Auto-build agent_map from Card steps."""
    required_roles: set[str] = set()
    for step in card.all_steps():
        if step.agent and step.agent != "scout":
            required_roles.add(step.agent)

    agent_map = {}
    for role in sorted(required_roles):
        aid = f"{cell_id}-{role}"
        agent_map[role] = aid
        if ensure_terminal_fn:
            ensure_terminal_fn(aid, role, None)
    return agent_map
