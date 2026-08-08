"""SessionLoopMixin — AgentLoop wiring, card callbacks, and memory ingestion.

Extracted from session.py (P1-1 split).  Builds the session's AgentLoop with
its tool set (_ensure_loop), reacts to card completion (_on_card_completed),
and ingests tool results / reasoning trails into L3A memory
(_ingest_tool_results / _ingest_reasoning).  Composed by Session alongside
the prompt/ask/compress/persist mixins.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from l1.kernel.params.system import (
    HASH_TRUNC_SHORTEST,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    LOG_TRUNC_500,
    LOG_TRUNC_2000,
)
from l3.error_bus import capture

from . import params as _p

logger = logging.getLogger(__name__)


class SessionLoopMixin:
    """AgentLoop wiring, card-completion callbacks, and L3A memory ingestion."""

    # ── Attributes injected by the concrete Session (see session.py) ──
    id: str
    user_id: str
    turn_count: int
    card_count: int
    _lock: Any
    _loop: Any
    _base_system: str
    _pmu: Any
    _cell_id: str
    _subscribed_cards: set[str]
    tasks: Any
    history: Any
    _resume_todos: list[dict]

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        from l3.agent.agent_loop import AgentLoop

        from .helpers import build_l3a_prompt

        self._base_system = build_l3a_prompt(user_id=self.user_id)
        try:
            from l1.kernel.paths import get_paths as _gp

            todo_path = os.path.join(_gp().data_dir, f"l3a_todos_{self.id}.json")
        except Exception:
            capture("l3a session: todo_path resolve failed", error_code="E_L3A_SESSION", component="l3a")
            todo_path = f".praxis/l3a_todos_{self.id}.json"
        self._loop = AgentLoop(
            task="",
            agent_id=_p.AGENT_ID,
            role="l3a",
            system=self._base_system,
            prompt_key="l3a.parse_system",
            cell_id=self._cell_id,
            todo_path=todo_path,
        )
        # Seed resumed TODO items into the fresh TodoTracker
        if self._resume_todos:
            try:
                self._loop._todo.load(self._resume_todos)
            except Exception:
                capture("l3a session: resume todos seed failed", error_code="E_L3A_SESSION", component="l3a")
                logger.debug("l3a session: resume todos seed failed")
        from .helpers import cardwrite_handler

        def _session_cardwrite(args: dict, agent_id: str = "") -> dict:
            """Session-scoped cardwrite: create card + track + subscribe to completion."""
            # Attach the session's user so the profile side-channel can
            # reference the user's established preferences on the card.
            if self.user_id and "user_id" not in args:
                args = dict(args)
                args["user_id"] = self.user_id
            r = cardwrite_handler(args, agent_id)
            if r.get("success"):
                cid = r.get("card_id", "")
                self.card_count += 1
                self._subscribed_cards.add(cid)
                self.tasks.track(cid, title=args.get("title", cid), turn=self.turn_count)
                try:
                    from l3.card.card_registry import get_registry

                    get_registry().subscribe(cid, self._on_card_completed)
                except Exception:
                    capture(
                        "l3a session: card subscribe failed",
                        error_code="E_L3A_SESSION",
                        component="l3a",
                        context={"card_id": cid},
                    )
                    logger.debug("l3a session: card subscribe failed for %s", cid)
            return r

        self._loop.add_tool(
            "cardwrite",
            "Create and submit a structured card.",
            {
                "nature": "string",
                "title": "string",
                "description": "string",
                "columns": "dict",
                "priority": "int",
                "phases": "list",
            },
            _session_cardwrite,
            parallel_safe=False,
        )
        from .subagent import l3a_collect_handler, l3a_peek_handler, l3a_spawn_handler

        self._loop.add_tool(
            "l3a_spawn",
            "Spawn an async subagent. Returns task_id immediately.",
            {"spec": "string", "task": "string", "group": "string"},
            l3a_spawn_handler,
            parallel_safe=True,
        )
        self._loop.add_tool(
            "l3a_collect",
            "Wait for a group of subagents and collect results.",
            {"group": "string", "timeout": "number"},
            l3a_collect_handler,
            parallel_safe=False,
        )
        self._loop.add_tool(
            "l3a_result",
            "Peek at a single subagent result (non-blocking).",
            {"task_id": "string"},
            l3a_peek_handler,
            parallel_safe=True,
        )
        from .helpers import l3a_convention_handler

        self._loop.add_tool(
            "l3a_convention",
            "Navigate a converged convention document. First call action=index "
            "for the issue/decision catalog, then fetch specific blocks: "
            "anchor=I-2 (issue), anchor=D-1 (decision), or agent=agent-b "
            "(all lines for that agent). max_chars bounds reads.",
            {"issue_id": "string", "action": "string", "anchor": "string", "agent": "string", "max_chars": "int"},
            l3a_convention_handler,
            parallel_safe=True,
        )
        from .helpers import l3a_summary_handler

        self._loop.add_tool(
            "l3a_summary",
            "Query L3A deliberation-memory: action=latest [domain] for recent "
            "convention distillations, action=search <query> for keyword hits, "
            "action=get <issue_id> for one full summary with overlap notes.",
            {"action": "string", "issue_id": "string", "query": "string", "domain": "string", "limit": "int"},
            l3a_summary_handler,
            parallel_safe=True,
        )
        from .ask import ask_handler as _l3a_ask_handler

        self._loop.add_tool(
            "l3a_ask",
            "Ask the user to clarify the request. Call when the user's prompt "
            "is ambiguous or critical information is missing (target platform, "
            "scope, constraints, acceptance criteria, etc.). Pass up to "
            f"{_p.ASK_MAX_QUESTIONS} questions as a list of dicts "
            "{question, options?, required?}. Execution pauses until the user "
            "answers in the chat window; answers are injected back before "
            "resuming.",
            {"questions": "list"},
            lambda args, agent_id="": _l3a_ask_handler(self, args, agent_id),
            parallel_safe=False,
        )
        if self._pmu:
            try:
                self._loop.set_pmu(self._pmu)
            except Exception:
                capture("l3a session: set_pmu on AgentLoop failed", error_code="E_L3A_SESSION", component="l3a")
                logger.warning("l3a session: set_pmu on AgentLoop failed")

    def _on_card_completed(self, card_id: str, state: str, result: dict) -> None:
        """Card completion callback — inject result into session history (closed loop)."""
        if self.status != "active":
            return
        title = ""
        try:
            from l3.card.card_registry import get_registry

            rec = get_registry().get(card_id)
            if rec and rec.summary:
                title = rec.summary.title or card_id
        except Exception:
            logger.debug("l3a.session: card title lookup failed, using card_id", exc_info=True)
        summary = result.get("summary", "")
        if not summary:
            summary = result.get("answer", "")
        if not summary:
            summary = str(result)[:LOG_TRUNC_200]
        # Convention convergence → distill L3A summary into dedicated store
        if result.get("issue_card_id") or result.get("doc_path"):
            self._distill_convention_summary(card_id, title, result)
        text = f"Card {card_id} ({title}) → {state}" + (f": {summary}" if summary else "")
        self.tasks.update(card_id, state, result)
        from .session_history import Message

        with self._lock:
            self.history.append(
                Message(
                    id=f"card-{uuid.uuid4().hex[:HASH_TRUNC_SHORTEST]}",
                    role="system",
                    content=text,
                    metadata={"card_id": card_id, "card_state": state},
                )
            )
        logger.info("l3a session %s: card %s → %s", self.id, card_id, state)

    def _ingest_tool_results(self, result: dict, user_text: str) -> None:
        """Ingest this turn's tool results into L3A's three-ring memory.

        Mirrors the Cell Peer Agent pattern (context.py end()):
          tool_call results  → L3A ring 1 (entry_type=l3a_tool_call)
          decision-grade     → L3A ring 2 (entry_type=l3a_tool_decision)
          turn summary       → L3A ring 3 (entry_type=l3a_turn_summary)
        """
        try:
            from l3.memory.central_memory import get_l3a_memory

            mem = get_l3a_memory()
        except Exception:
            return
        tool_results = result.get("tool_call_results", []) or []
        if not tool_results:
            return
        high_value_tools = {"cardwrite", "l3a_ask", "l3a_collect", "l3a_convention", "l3a_spawn", "l3a_summary"}
        decision_entries = []
        for sr in tool_results:
            tool_name = sr.get("tool_name", "") or sr.get("action", "?")
            payload = sr.get("result", {}) if isinstance(sr, dict) and "result" in sr else sr
            content = f"[turn:{self.turn_count}] {tool_name} → {str(payload)[:LOG_TRUNC_300]}"
            ring = 2 if tool_name in high_value_tools else 1
            entry_type = "l3a_tool_decision" if ring == 2 else "l3a_tool_call"
            try:
                mem.remember(
                    agent_id=_p.AGENT_ID,
                    entry_type=entry_type,
                    content=content,
                    tags=["l3a", tool_name, self.id],
                    importance=0.7 if ring == 2 else 0.5,
                    ring=ring,
                    cell_id=self._cell_id,
                )
                if ring == 2:
                    decision_entries.append(content[:LOG_TRUNC_200])
            except Exception:
                logger.debug("l3a session: tool result memory ingest failed")
        # Turn summary → ring 3 (long-term, importance weighted)
        try:
            summary = f"[session:{self.id} turn:{self.turn_count}] user: {user_text[:LOG_TRUNC_100]}" + (
                f" | decisions: {'; '.join(decision_entries)[:LOG_TRUNC_300]}" if decision_entries else ""
            )
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_turn_summary",
                content=summary,
                tags=["l3a", "turn_summary", self.id],
                importance=0.6,
                ring=3,
                cell_id=self._cell_id,
            )
        except Exception:
            logger.debug("l3a session: turn summary ingest failed")

    def _ingest_reasoning(self, result: dict, user_text: str) -> None:
        """Persist this turn's thinking-mode reasoning trail (deepseek-v4,
        claude thinking, etc.) into L3A ring 2 as the deliberation record.

        The chain-of-thought is the decision process — more valuable than the
        final answer. Folded into ONE entry per turn (bounded rounds) so the
        memory stays usable, not a verbatim transcript.
        """
        trail = result.get("reasoning_trail") or []
        if not trail:
            return
        try:
            from l3.memory.central_memory import get_l3a_memory

            mem = get_l3a_memory()
        except Exception:
            return
        folded = "\n---\n".join(t.strip()[:LOG_TRUNC_500] for t in trail[: _p.REASONING_TRAIL_MAX_TURNS])[
            :LOG_TRUNC_2000
        ]
        if not folded:
            return
        rtok = int(result.get("reasoning_tokens", 0) or 0)
        content = (
            f"[session:{self.id} turn:{self.turn_count}] "
            f"reasoning_tokens:{rtok} user: {user_text[:LOG_TRUNC_100]}\n"
            f"reasoning:\n{folded}"
        )
        try:
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_reasoning_trail",
                content=content,
                tags=["l3a", "reasoning", self.id],
                importance=_p.REASONING_TRAIL_IMPORTANCE,
                ring=2,
                cell_id=self._cell_id,
            )
        except Exception:
            logger.debug("l3a session: reasoning trail ingest failed")
