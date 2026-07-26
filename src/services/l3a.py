"""L3A — Human interface layer as an AgentLoop session.

L3A runs as an AgentLoop with the `cardwrite` tool, enabling:
  - Multi-turn dialogue to clarify user intent
  - LLM generates CardUnified with phases, tasks, and metadata
  - Falls back to rule engine when LLM unavailable
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from kernel.prompts import get_prompt
from kernel.params.agent import L3A_MAX_STEPS, L3A_TIMEOUT
from .card_unified import CardUnified, CardSummary, PhaseMode, list_card_types

from kernel.params.agent import DEFAULT_CELL_ID

logger = logging.getLogger(__name__)

# L3A system prompt — instructs LLM to use cardwrite tool
_PARSE_SYSTEM_PROMPT = get_prompt("l3a.parse_system")


class CardType(Enum):
    EXECUTION = auto()
    ISSUE = auto()
    DIRECTIVE = auto()
    DIRECT_SESSION = auto()


@dataclass
class TaskCard:
    id: str = ""
    intent: str = ""
    card_type: CardType = CardType.EXECUTION
    domain: str = ""
    cell: str = ""
    priority: int = 5
    tools_hint: list[str] = field(default_factory=list)
    agent_id: str = ""
    created_at: float = field(default_factory=time.time)


def _build_l3a_prompt() -> str:
    """Build the L3A system prompt with available card types."""
    from kernel.prompts import get_prompt as _gp
    types = list_card_types()
    types_block = "\n".join(
        f"  - {t['name']}: {t['display']} (phases: {', '.join(t.get('phases', []))})"
        for t in types
    )
    return _gp("l3a.agentloop_system").format(card_types=types_block)


def _cardwrite_handler(args: dict, agent_id: str = "") -> dict:
    """AgentLoop tool: create and submit a CardUnified."""
    from .card_registry import get_registry

    nature = args.get("nature", "execution")
    title = args.get("title", args.get("intent", ""))
    description = args.get("description", "")
    columns = args.get("columns", {})
    priority = args.get("priority", 5)
    phases_data = args.get("phases", [])
    domain = columns.get("domain", "")

    card = CardUnified(nature=nature, priority=priority)
    card.summary = CardSummary(
        title=title,
        description=description,
        columns=columns,
    )

    for pd in phases_data:
        mode_str = pd.get("mode", "single")
        mode = PhaseMode.MULTI if mode_str == "multi" else PhaseMode.SINGLE
        phase = card.add_phase(
            name=pd.get("name", ""),
            mode=mode,
            agents=pd.get("agents", []),
            review_prompt=pd.get("review_prompt", ""),
        )
        for td in pd.get("tasks", []):
            card.add_task(
                phase_name=phase.name,
                action=td.get("action", ""),
                target=td.get("target", ""),
                params=td.get("params", {}),
                agent=td.get("agent", ""),
            )

    card.submit()

    # Register with CardRegistry
    try:
        reg = get_registry()
        cid = reg.submit(intent=title, domain=domain, priority=priority, card_id=card.id)
        # Store the full card in registry
        with reg._lock:
            reg._cards[cid] = card
        logger.info("L3A cardwrite: %s — %s", card.id, title[:60])
        return {"success": True, "card_id": card.id, "nature": nature,
                "phases": len(phases_data), "message": f"Card {card.id} submitted"}
    except Exception as e:
        return {"success": False, "error": str(e), "card_id": card.id}


class L3A:
    """Always-on human interface: intent → card → route.

    Uses AgentLoop with cardwrite tool for multi-turn dialogue.
    Falls back to rule engine when LLM unavailable.
    """

    def __init__(self):
        self._routes: dict[str, str] = {}
        self._cards: list[TaskCard] = []
        self._next_id = 0
        self._history: list[dict] = []

    def register_route(self, domain_keyword: str, cell_id: str) -> None:
        self._routes[domain_keyword] = cell_id

    def parse(self, text: str, use_llm: bool = False) -> TaskCard | dict:
        """Parse human intent. Returns TaskCard (rule) or AgentLoop result dict (LLM)."""
        self._history.append({"role": "user", "content": text})

        if use_llm:
            try:
                return self._agentloop_parse(text)
            except Exception as e:
                logger.warning("L3A AgentLoop failed, using rule engine: %s", e)

        return self._rule_parse(text)

    def _agentloop_parse(self, text: str) -> dict:
        """Multi-turn AgentLoop: LLM can ask questions and use cardwrite tool."""
        from .agent_loop import AgentLoop

        # Build L3A prompt with available card types
        system = _build_l3a_prompt()

        loop = AgentLoop(
            task=text,
            agent_id="l3a",
            role="l3a",
            system=system,
            prompt_key="l3a.parse_system",
        )

        # Register the cardwrite tool
        loop.add_tool("cardwrite",
            "Create and submit a structured card. Call this when you understand the user's intent. "
            "Arguments: nature (card type name), title, description (optional), "
            "columns (dict with optional 'domain' key), priority (1-10), "
            "phases (list of {name, mode: single|multi, tasks: [{action, target, agent}]})",
            {"nature": "string", "title": "string", "description": "string",
             "columns": "dict", "priority": "int", "phases": "list"},
            _cardwrite_handler,
            parallel_safe=False,
        )

        result = loop.run(max_steps=L3A_MAX_STEPS, timeout=L3A_TIMEOUT)
        self._history.append({"role": "assistant", "content": result.get("answer", "")})
        return result

    def _rule_parse(self, text: str) -> TaskCard:
        """Keyword-based rule engine fallback."""
        card_type = CardType.EXECUTION
        domain = ""
        for kw, cell in self._routes.items():
            if kw.lower() in text.lower():
                domain = kw
                break
        if "?" in text:
            card_type = CardType.ISSUE
        return self._make_card(text, card_type, domain)

    def _make_card(self, text: str, card_type: CardType, domain: str,
                   priority: int = 5) -> TaskCard:
        card = TaskCard(
            id=f"card-{self._next_id:04d}", intent=text,
            card_type=card_type, domain=domain, priority=priority,
        )
        self._next_id += 1
        self._cards.append(card)
        return card

    def route(self, card: TaskCard, cells: list[dict]) -> str:
        if card.cell:
            return card.cell
        if not card.domain:
            return cells[0]["id"] if cells else _DEFAULT_L3A_CELL
        best = cells[0]["id"] if cells else _DEFAULT_L3A_CELL
        best_score = 0
        for c in cells:
            score = sum(1 for t in c.get("territory", []) if card.domain.startswith(t))
            if score > best_score:
                best_score, best = score, c["id"]
        return best

    def recent(self, n: int = 10) -> list[dict]:
        return [{"id": c.id, "intent": c.intent, "card_type": c.card_type.name,
                 "domain": c.domain, "cell": c.cell, "priority": c.priority}
                for c in self._cards[-n:]]
