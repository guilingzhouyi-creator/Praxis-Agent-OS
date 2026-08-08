"""LifecycleHooks 鈥?composable turn-level hooks for AgentLoop.

Pattern: HookChain composes multiple hooks into one, fanning out each method.
Each hook has clear PERMANENT vs. EPHEMERAL mutation semantics.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LifecycleHooks:
    """Turn-level lifecycle hooks for AgentLoop.

    Methods returning None are observation-only.
    Methods returning a value can modify behavior.
    """

    def session_start(self, task: str, agent_id: str) -> str:
        """Called when AgentLoop starts. Mutate the task string permanently."""
        return task

    def user_prompt_submit(self, prompt: str) -> str | None:
        """Block or rewrite user input. Return None to allow, str to override."""
        return None

    def pre_request(self, messages: list[dict], ctx: dict) -> list[dict]:
        """Ephemeral per-round projection. Mutations do NOT persist."""
        return messages

    def on_text_delta(self, delta: str) -> str:
        """Transform a text delta from LLM stream."""
        return delta

    def on_reasoning_delta(self, delta: str) -> str:
        """Transform a reasoning delta from LLM stream."""
        return delta

    def on_model_response(self, msg: dict) -> dict:
        """Transform a complete model response."""
        return msg

    def offer_continuation(self, conversation: list) -> str | None:
        """Return a continuation prompt string, or None for no continuation."""
        return None

    def turn_complete(self, result: dict, elapsed: float) -> None:
        """Unconditional terminal 鈥?always called, even on error."""
        pass

    def on_error(self, error: str) -> None:
        """Handle a loop error (observation-only by default)."""
        pass

    def session_end(self, result: dict) -> None:
        """Called when the loop ends (observation-only by default)."""
        pass


class EventEmitHook(LifecycleHooks):
    """Observation hook that mirrors turn/error/session events onto the bus.

    Composable via HookChain: add to the chain at boot so frontends can
    visualize agent loop activity without polling.
    """

    def turn_complete(self, result: dict, elapsed: float) -> None:
        """Emit agent.turn_complete with the turn result."""
        try:
            from l1.kernel import get_event_bus

            get_event_bus().emit_event("agent.turn_complete", {"result": result, "elapsed": elapsed}, source="hook")
        except Exception:
            logger.debug("hook: turn_complete emit failed")
        self._ingest_agent_metric("agent.turn_complete")

    def on_error(self, error: str) -> None:
        """Emit agent.loop_error with the error text."""
        try:
            from l1.kernel import get_event_bus

            get_event_bus().emit_event("agent.loop_error", {"error": error}, source="hook")
        except Exception:
            logger.debug("hook: on_error emit failed")
        self._ingest_agent_metric("agent.loop_error")

    def session_end(self, result: dict) -> None:
        """Emit agent.session_end with the final result."""
        try:
            from l1.kernel import get_event_bus

            get_event_bus().emit_event("agent.session_end", {"result": result}, source="hook")
        except Exception:
            logger.debug("hook: session_end emit failed")
        self._ingest_agent_metric("agent.session_end")

    @staticmethod
    def _ingest_agent_metric(name: str) -> None:
        """Phase G: AgentLoop lifecycle events also land in StatsCenter."""
        try:
            from l3.services.stats_center import MetricPoint, get_center

            get_center().ingest(
                MetricPoint(
                    name=name,
                    value=1.0,
                    tags={"source": "hook"},
                    timestamp=__import__("time").time(),
                    metric_type="counter",
                )
            )
        except Exception:
            logger.debug("hook: agent metric ingest failed")


class HookChain(LifecycleHooks):
    """Compose multiple hooks into one, fanning out each method.

    The output of each hook is fed as input to the next, forming a chain.
    """

    def __init__(self, hooks: list[LifecycleHooks] | None = None):
        self._hooks: list[LifecycleHooks] = []

    def add(self, hook: LifecycleHooks) -> None:
        """Append a single hook to the chain."""
        self._hooks.append(hook)
        logger.debug("HookChain: added %s", type(hook).__name__)

    def add_all(self, hooks: list[LifecycleHooks]) -> None:
        """Append multiple hooks to the chain."""
        self._hooks.extend(hooks)

    def _chain(self, method: str, args: tuple[Any, ...], kw: dict | None = None) -> Any:
        """Chain a method across all hooks, passing output as input."""
        kw = kw or {}
        result = None
        for hook in self._hooks:
            fn = getattr(hook, method, None)
            if fn:
                try:
                    if result is not None and args:
                        args = (result, *args[1:])
                    elif result is not None:
                        args = (result,)
                    r = fn(*args, **kw)
                    if r is not None:
                        result = r
                except Exception as e:
                    logger.warning("HookChain.%s failed in %s: %s", method, type(hook).__name__, e)
        return result

    def session_start(self, task: str, agent_id: str) -> str:
        """Chain session_start across hooks; returns the (possibly mutated) task."""
        return self._chain("session_start", (task, agent_id)) or task

    def user_prompt_submit(self, prompt: str) -> str | None:
        """Chain user_prompt_submit across hooks; returns the override prompt or None."""
        return self._chain("user_prompt_submit", (prompt,))

    def pre_request(self, messages: list[dict], ctx: dict) -> list[dict]:
        """Chain pre_request across hooks; returns the final messages."""
        return self._chain("pre_request", (messages, ctx)) or messages

    def on_text_delta(self, delta: str) -> str:
        """Chain on_text_delta across hooks; returns the final delta."""
        return self._chain("on_text_delta", (delta,)) or delta

    def on_reasoning_delta(self, delta: str) -> str:
        """Chain on_reasoning_delta across hooks; returns the final delta."""
        return self._chain("on_reasoning_delta", (delta,)) or delta

    def on_model_response(self, msg: dict) -> dict:
        """Chain on_model_response across hooks; returns the final message."""
        return self._chain("on_model_response", (msg,)) or msg

    def offer_continuation(self, conversation: list) -> str | None:
        """Chain offer_continuation across hooks; returns the first continuation or None."""
        return self._chain("offer_continuation", (conversation,))

    def turn_complete(self, result: dict, elapsed: float) -> None:
        """Chain turn_complete across hooks (observation-only)."""
        self._chain("turn_complete", (result, elapsed))

    def on_error(self, error: str) -> None:
        """Chain on_error across hooks (observation-only)."""
        self._chain("on_error", (error,))

    def session_end(self, result: dict) -> None:
        """Chain session_end across hooks (observation-only)."""
        self._chain("session_end", (result,))


# 鈹€鈹€ Built-in hook implementations 鈹€鈹€


class SkillCatalogHook(LifecycleHooks):
    """Inject available skills into the system prompt at session start.

    Built-in skills (shipped under ``config/skills``) are injected first
    with priority, then runtime/evolved skills up to
    ``SKILL_CATALOG_HOOK_LIMIT``.  Injection of built-ins can be disabled
    per-deployment via the ``skill.auto_activate_builtin`` setting
    (default: ``SKILL_AUTO_ACTIVATE_BUILTIN``).
    """

    def session_start(self, task: str, agent_id: str) -> str:
        """Append an available-skill catalog to the task string."""
        try:
            from l1.kernel.params.system import (
                LOG_TRUNC_60,
                SKILL_AUTO_ACTIVATE_BUILTIN,
                SKILL_CATALOG_HOOK_LIMIT,
                SKILL_POSTURE_OFFENSIVE,
            )
            from l1.kernel.skill import audience_of, get_skill_manager, skill_visible

            sm = get_skill_manager()
            auto_builtin = SKILL_AUTO_ACTIVATE_BUILTIN
            try:
                from l3.config.settings_center import get_center as _sc

                auto_builtin = bool(_sc().get("skill.auto_activate_builtin", auto_builtin))
            except Exception:
                pass
            skills = sm.list_skills(sort_by="loaded_at")
            # Posture gate (default-deny, runtime policy): offensive-posture
            # skills are not advertised in the session catalog while the gate
            # is enabled. Disabling the policy (soft bypass) advertises them.
            if sm.offensive_policy().get("enabled", True):
                skills = [s for s in skills if s.get("posture") != SKILL_POSTURE_OFFENSIVE]
            # Audience routing: strategy skills surface only for the L3A
            # decision layer, execution skills for Cell peer agents
            # (untagged skills are universal). Toggleable via disclosure policy.
            disclosure = sm.disclosure_policy()
            if not isinstance(disclosure, dict):
                disclosure = {}
            if disclosure.get("audience_filter_enabled", True):
                skills = [s for s in skills if skill_visible(s, agent_id)]
            # Disclosure depth: none → hidden from every surface; index →
            # name+desc only (content loads on explicit use_skill).
            skills = [s for s in skills if s.get("disclosure", "full") != "none"]
            # Contribution-aware ordering: built-in (read-only) skills keep
            # priority when auto-activation is on, then usage (useful_count /
            # last_used) instead of the plain loaded_at tie-break — high-value
            # skills hold stable exposure in the limited catalog slots.
            if auto_builtin:
                skills.sort(
                    key=lambda s: (
                        0 if s.get("builtin") else 1,
                        -(int(s.get("useful_count", 0) or 0)),
                        -float(s.get("last_used", 0.0) or 0.0),
                    )
                )
            else:
                skills.sort(
                    key=lambda s: (
                        -(int(s.get("useful_count", 0) or 0)),
                        -float(s.get("last_used", 0.0) or 0.0),
                    )
                )
            # E2: constitutional gate at session-injection time — a skill
            # whose use is blocked by the constitution is not injected
            # (defensive layer on top of the load-time check). When the
            # offensive policy is disabled (soft bypass), offensive skills
            # skip the §9.2 posture check so the advertised bypass stays
            # consistent end to end.
            policy_enabled = sm.offensive_policy().get("enabled", True)
            try:
                from l1.kernel.constitution import get_constitution

                const = get_constitution()
                allowed_skills = []
                for s in skills:
                    if s.get("posture") == SKILL_POSTURE_OFFENSIVE and not policy_enabled:
                        allowed_skills.append(s)
                        continue
                    if const.is_allowed("skill.use", agent_id or "system", target=s["name"]).get("allowed"):
                        allowed_skills.append(s)
                skills = allowed_skills
            except Exception as e:
                logger.debug("SkillCatalogHook: constitution filter skipped: %s", e)
            # R5 domain matching: re-rank the filtered candidates by task-text
            # relevance (tf-idf — the same retriever used for per-turn evolved
            # injection), so a session whose task belongs to a skill's domain
            # surfaces those skills first. Non-matching tasks keep the
            # contribution order (the retriever returns [] below the floor).
            if task.strip():
                try:
                    from l3.memory.skill_retriever import get_retriever

                    retriever = get_retriever()
                    groups = (
                        ([s for s in skills if s.get("builtin")], [s for s in skills if not s.get("builtin")])
                        if auto_builtin
                        else (skills,)
                    )
                    ranked: list[dict] = []
                    for group in groups:
                        if not group:
                            continue
                        r = retriever.rank(task, group, limit=len(group))
                        ranked.extend(r if r else group)
                    if ranked:
                        skills = ranked
                except Exception as e:
                    logger.debug("SkillCatalogHook: relevance ranking skipped: %s", e)
            # Two-level index (progressive disclosure): curated slots first,
            # then the full skill index when the disclosure policy enables it.
            curated = skills[:SKILL_CATALOG_HOOK_LIMIT]
            if curated:
                lines = ["\nAvailable skills (use_skill to invoke):"]
                for s in curated:
                    marker = " [builtin]" if s.get("builtin") else ""
                    desc = (s.get("description", "") or "")[:LOG_TRUNC_60]
                    lines.append(f"  {s['name']}{marker}: {desc}")
                if disclosure.get("full_index_enabled"):
                    full_limit = int(disclosure.get("full_index_limit") or SKILL_CATALOG_HOOK_LIMIT)
                    for s in skills[SKILL_CATALOG_HOOK_LIMIT:full_limit]:
                        desc = (s.get("description", "") or "")[:LOG_TRUNC_60]
                        lines.append(f"  {s['name']}: {desc}")
                task += "\n".join(lines)
            # L3A decision layer: read-only capability view of execution
            # skills (what Cell peers can do) — delegation support.
            if disclosure.get("strategy_capability_view") and audience_of(agent_id) == "strategy":
                try:
                    cap_lines = ["\nPeer capabilities (execution skills — delegate via cards):"]
                    for s in sm.list_skills():
                        if "execution" in (s.get("tags") or []) and s.get("disclosure", "full") != "none":
                            desc = (s.get("description", "") or "")[:LOG_TRUNC_60]
                            cap_lines.append(f"  [peer-capability] {s['name']}: {desc}")
                    task += "\n".join(cap_lines)
                except Exception as e:
                    logger.debug("SkillCatalogHook: capability view skipped: %s", e)
        except Exception as e:
            logger.debug("SkillCatalogHook: %s", e)
        return task


class CadenceHook(LifecycleHooks):
    """Edit-then-verify nudging 鈥?detects edits without follow-up checks."""

    def __init__(self):
        self._edited: set[str] = set()
        self._nudged: set[str] = set()

    def on_model_response(self, msg: dict) -> dict:
        """Detect edit tool calls in the response."""
        tool_calls = msg.get("tool_calls", []) if isinstance(msg, dict) else []
        for tc in tool_calls if tool_calls else []:
            name = tc.get("name", "") if isinstance(tc, dict) else ""
            if name in ("edit", "edit_file", "write_file", "create_file"):
                self._edited.add(name)
        return msg

    def offer_continuation(self, conversation: list) -> str | None:
        """Return a verification nudge once per edit batch, else None."""
        unverified = [e for e in self._edited if e not in self._nudged]
        if not unverified:
            return None
        self._nudged.update(unverified)
        return (
            "Unverified edits detected. "
            "Run verification commands (build/test/lint) and "
            "use 'todowrite' with status='verified' when checks pass."
        )


class StatusReminderHook(LifecycleHooks):
    """Inject current date/time info per turn."""

    def pre_request(self, messages: list[dict], ctx: dict) -> list[dict]:
        """Append a synthetic system-time reminder message."""
        import time

        ts = time.strftime("%Y-%m-%d %H:%M:%S %Z")
        reminder = {"role": "user", "content": f"[System time: {ts}]", "synthetic": True}
        messages.append(reminder)
        return messages


# ── Hook chain singleton ──────────────────────────────────────────────────────


_hook_chain: HookChain | None = None


def get_hook_chain() -> HookChain:
    """Get the shared HookChain (auto-registers EventEmitHook on first use).

    AgentLoop and the L4 API layer consume this chain so turn-level
    observation hooks (EventEmitHook -> event bus -> SSE/WS) are active
    once boot has run ``wire_defaults``.
    """
    global _hook_chain
    if _hook_chain is None:
        _hook_chain = HookChain()
        _hook_chain.add(EventEmitHook())
    return _hook_chain


def reset_hook_chain() -> None:
    """Drop the shared chain singleton (for testing / hot-reload)."""
    global _hook_chain
    _hook_chain = None
