"""AgentLoop context mixin — system-prompt construction and R4 context injection.

Extracted from ``agent_loop.py`` (AgentLoop) to slim the class: prompt
template resolution, chat-params hooks, todowrite registration, and the
R4 lean-case / evolved-skill / cross-cell-rule injection with bounded
token budget. ``AgentLoop`` inherits this mixin so runtime behavior is
unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import (
    LOOP_CONTEXT_BUDGET_SKILL,
    LOOP_EVOLVED_SKILLS_LIMIT,
    LOOP_LEAN_CASES_LIMIT,
    R4_CARD_SKILL_SIGNAL_MAX,
)
from l1.kernel.params.kernel import RING_1
from l1.kernel.params.system import LOG_TRUNC_40, LOG_TRUNC_200, SKILL_POSTURE_OFFENSIVE
from l1.kernel.prompts import get_prompt
from l3.tool_system.tool_spec import ParamSpec, ToolSpec

logger = logging.getLogger(__name__)


def _inject_enabled(domain: str) -> bool:
    """Whether the ``prompt.inject.<domain>`` system-prompt injection is on."""
    from l1.kernel.settings import inject_enabled as _ie

    return _ie(domain)


class AgentLoopContextMixin:
    """System-prompt assembly and R4-driven context injection for AgentLoop."""

    def _card_query_boost(self) -> str:
        """Build the tag-boost fragment appended to the retrieval query."""
        tags = getattr(self, "_card_tags", []) or []
        if not tags:
            return ""
        return " " + " ".join(tags)

    def _build_run_context(
        self, max_steps: int, model_config: dict | None, engine: Any
    ) -> tuple[str, list, list, dict]:
        """Build system prompt, wrap tools, and prepare model kwargs."""
        model_kwargs: dict = {}
        if model_config:
            for key in ("model", "max_tokens", "temperature", "reasoning_effort", "thinking_budget"):
                if key in model_config and model_config[key] is not None:
                    model_kwargs[key] = model_config[key]

        for hook in self._chat_params_hooks:
            try:
                override = hook(self.task, self.agent_id, dict(model_kwargs))
                if isinstance(override, dict):
                    model_kwargs.update(override)
            except Exception as e:
                logger.warning("chat params hook failed: %s", e)
        self._register_todowrite()
        todo_reminder = self._todo.reminder()

        if self._system:
            system = self._system
        else:
            pk = self._prompt_key
            if not pk and self._role:
                pk = f"agent_loop.system.{self._role}"
            if not pk:
                pk = "agent_loop.system"
            template = get_prompt(pk, get_prompt("agent_loop.system", ""))
            system = template.format(task=self.task) + get_prompt(
                "agent_loop.turn_budget", "\nYou have up to {max_steps} tool-calling turns. Use them wisely."
            ).format(max_steps=max_steps)
        vc = get_prompt("agent_loop.verification_culture", "")
        if vc and _inject_enabled("verification"):
            system = (system + "\n\n" + vc) if system else vc
        if todo_reminder:
            system = (system + "\n\n" + todo_reminder) if system else todo_reminder

        try:
            from l1.kernel.constitution import get_constitution

            if _inject_enabled("constitution"):
                const_summary = get_constitution().summary(for_agent=self.agent_id)
                system = (system + "\n\n" + const_summary) if system else const_summary
        except (ImportError, AttributeError):
            logger.debug("agent_loop: constitution summary failed")

        wrapped_tools = []
        read_only_tools = []
        for t in self._tools:
            wrapped = ToolSpec(
                name=t.name,
                description=t.description,
                category=t.category,
                ring=t.ring,
                danger=t.danger,
                parameters=t.parameters,
                handler=self._wrap_handler(t.handler),
                parallel_safe=t.parallel_safe,
            )
            wrapped_tools.append(wrapped)
            if t.parallel_safe:
                read_only_tools.append(wrapped)
        return system, wrapped_tools, read_only_tools, model_kwargs

    def _inject_extra_context(self, system: str) -> str:
        """Inject R4 lean cases, evolved skills, and cross-cell rules into system prompt.

        Token budget is bounded by ``LOOP_CONTEXT_BUDGET_SKILL`` to avoid
        overflowing the context window with skill content. Gated by the
        ``prompt.inject.skills`` setting (user-configurable).
        """
        if not _inject_enabled("skills"):
            return system
        try:
            from l3.memory.r4_agent import get_r4_agent

            r4 = get_r4_agent()
            budget = LOOP_CONTEXT_BUDGET_SKILL
            lean = r4.get_lean_cases(agent_id=self.agent_id, cell_id=self._cell_id, limit=LOOP_LEAN_CASES_LIMIT)
            injected: list[str] = []
            if lean:
                # All returned lean cases are injected (full or truncated), so
                # their names ride the same cache — no extra registry scan.
                injected = list(
                    r4.get_lean_case_names(agent_id=self.agent_id, cell_id=self._cell_id, limit=LOOP_LEAN_CASES_LIMIT)
                )
                lines = "\n".join(f"  {i}. {lc}" for i, lc in enumerate(lean, 1))
                block = f"\n\n--- Known Failure Patterns ---\n{lines}\n---"
                if len(block) <= budget:
                    system += block
                    budget -= len(block)
                else:
                    truncated = "\n".join(f"  {i}. {lc[:LOG_TRUNC_200]}" for i, lc in enumerate(lean, 1))
                    system += f"\n\n--- Known Failure Patterns (truncated) ---\n{truncated}\n---"
            # Task-similarity retrieval (tf-idf, zero deps): rank evolved
            # skills by relevance to the current task before injection;
            # falls back to loaded_at ordering when disabled or low-score.
            # getattr guard: tests may construct AgentLoop via __new__ (no
            # __init__), so task may be absent — empty query = loaded_at order.
            # Card linkage: card-derived tags (nature/domain) are appended to
            # the query so the same task text under different card types can
            # surface different skills (e.g. review vs deploy cards).
            evolved = r4.retrieve_skills(
                query=(getattr(self, "task", "") or "") + self._card_query_boost(),
                agent_id=self.agent_id,
                cell_id=self._cell_id,
                limit=LOOP_EVOLVED_SKILLS_LIMIT,
                tags=getattr(self, "_card_tags", []) or [],
            )
            if evolved and budget > 0:
                for es in evolved:
                    # Audience routing: user-invoked skills and skills tagged
                    # for another domain are excluded from automatic context
                    # injection — they fire only on explicit use within their
                    # own domain (dynamic supply, not blanket injection).
                    if es.get("disable_model_invocation"):
                        continue
                    from l1.kernel.skill import get_skill_manager as _loop_sm
                    from l1.kernel.skill import skill_visible

                    if not skill_visible(es, self.agent_id):
                        continue
                    # Posture gate (default-deny, runtime policy): offensive
                    # skills are only injected when the SkillManager
                    # offensive-policy authorizes the driving card nature
                    # (L3A decision layer). The gate can be bypassed at
                    # runtime by disabling the policy (soft control).
                    if es.get("posture") == SKILL_POSTURE_OFFENSIVE and not _loop_sm().offensive_authorized(
                        getattr(self, "_card_nature", "")
                    ):
                        # P1: record posture-gate injection blocks in StatsCenter.
                        try:
                            from l3.tool_system.security_mode import ingest_security_metric

                            ingest_security_metric(
                                "security.gate.injection.blocked",
                                tags={"skill": es.get("name", ""), "nature": getattr(self, "_card_nature", "")},
                            )
                        except Exception:
                            pass
                        continue
                    # Structured injection: name + description + rule count —
                    # the markdown body stays on the human/review layer.
                    rules_count = es.get("rules") or 0
                    block = f"\n\n### {es['name']}\n{es['description']} ({rules_count} rules)"
                    if len(block) <= budget:
                        system += block
                        budget -= len(block)
                        injected.append(es["name"])
                        # Phase C: record successful offensive-skill injections
                        # (the allowed counterpart of injection.blocked).
                        if es.get("posture") == SKILL_POSTURE_OFFENSIVE:
                            try:
                                from l3.tool_system.security_mode import ingest_security_metric

                                ingest_security_metric(
                                    "security.gate.injection.allowed",
                                    tags={"skill": es.get("name", ""), "nature": getattr(self, "_card_nature", "")},
                                )
                            except Exception:
                                pass
                        if getattr(self, "_pmu", None):
                            try:
                                self._pmu.increment("skills.evolved.injected")
                            except Exception:
                                logger.debug("agent_loop: pmu increment failed, skipped", exc_info=True)
                    else:
                        # Partial: only include name + description
                        system += f"\n\n### {es['name']}\n{es['description']}"
                        injected.append(es["name"])
                        break
            # Injection feedback: refresh last_used for every injected skill so
            # the R4Agent TTL prune never deletes skills that are actively
            # exposed to agents.  Usage-only update — no write clearance, no
            # revision bump (the R4Agent injection cache stays hot).  Also
            # records inject_count — the denominator of the curation
            # contribution score (useful/injected).
            if injected:
                try:
                    from l1.kernel.skill import get_skill_manager

                    _sm = get_skill_manager()
                    _now = time.time()
                    for _name in injected:
                        _sm.update(_name, {"last_used": _now})
                        _sm.bump_usage(_name, key="inject_count")
                        # Card→skill signal: injected skills ride the current
                        # card's preference attribution (bounded set).
                        _used = getattr(self, "_card_skills_used", None)
                        if _used is not None and len(_used) < R4_CARD_SKILL_SIGNAL_MAX:
                            _used.add(_name)
                except Exception as e:
                    logger.debug("agent_loop: skill last_used refresh failed: %s", e)
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)
        try:
            from l3.cell.peers.l3 import get_coordinator

            coord = get_coordinator()
            if getattr(coord, "_cross_cell_active", False):
                system += get_prompt("agent_loop.cross_cell_rules", "")
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)
        return system

    def _register_todowrite(self) -> None:
        """Register the todowrite tool for task-list management."""

        def _todowrite_handler(args: dict, agent_id: str = "") -> dict:
            """Handle a todowrite tool call — update todo item status."""
            content = args.get("content", "")
            status = args.get("status", "in_progress")
            self._todo.update(content, status)
            return {"success": True, "message": f"todo '{content[:LOG_TRUNC_40]}' → {status}"}

        # Only register if not already added
        if not any(t.name == "todowrite" for t in self._tools):
            self._tools.append(
                ToolSpec(
                    name="todowrite",
                    description="Update task list status. status: pending|in_progress|completed. Use 'add' for new items.",
                    category="generic",
                    ring=RING_1,
                    danger=0,
                    parameters=[
                        ParamSpec("content", "string", required=True, description="Task description"),
                        ParamSpec("status", "string", required=True, description="pending|in_progress|completed|add"),
                    ],
                    handler=_todowrite_handler,
                    parallel_safe=False,
                )
            )
