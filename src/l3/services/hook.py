"""LifecycleHooks — composable turn-level hooks for AgentLoop.

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
        """Unconditional terminal — always called, even on error."""
        pass

    def on_error(self, error: str) -> None:
        pass

    def session_end(self, result: dict) -> None:
        pass


class HookChain(LifecycleHooks):
    """Compose multiple hooks into one, fanning out each method.

    The output of each hook is fed as input to the next, forming a chain.
    """

    def __init__(self, hooks: list[LifecycleHooks] | None = None):
        self._hooks: list[LifecycleHooks] = []

    def add(self, hook: LifecycleHooks) -> None:
        self._hooks.append(hook)
        logger.debug("HookChain: added %s", type(hook).__name__)

    def add_all(self, hooks: list[LifecycleHooks]) -> None:
        self._hooks.extend(hooks)

    def _chain(self, method: str, args: list, kw: dict | None = None) -> Any:
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
                    logger.warning("HookChain.%s failed in %s: %s",
                                   method, type(hook).__name__, e)
        return result

    def session_start(self, task: str, agent_id: str) -> str:
        return self._chain("session_start", (task, agent_id)) or task

    def user_prompt_submit(self, prompt: str) -> str | None:
        return self._chain("user_prompt_submit", (prompt,))

    def pre_request(self, messages: list[dict], ctx: dict) -> list[dict]:
        return self._chain("pre_request", (messages, ctx)) or messages

    def on_text_delta(self, delta: str) -> str:
        return self._chain("on_text_delta", (delta,)) or delta

    def on_reasoning_delta(self, delta: str) -> str:
        return self._chain("on_reasoning_delta", (delta,)) or delta

    def on_model_response(self, msg: dict) -> dict:
        return self._chain("on_model_response", (msg,)) or msg

    def offer_continuation(self, conversation: list) -> str | None:
        return self._chain("offer_continuation", (conversation,))

    def turn_complete(self, result: dict, elapsed: float) -> None:
        self._chain("turn_complete", (result, elapsed))

    def on_error(self, error: str) -> None:
        self._chain("on_error", (error,))

    def session_end(self, result: dict) -> None:
        self._chain("session_end", (result,))


# ── Built-in hook implementations ──


class SkillCatalogHook(LifecycleHooks):
    """Inject available skills into the system prompt at session start.

    Injects at most ``SKILL_CATALOG_HOOK_LIMIT`` skills to avoid duplication
    with ``AgentLoop._inject_extra_context`` which separately injects lean
    cases and evolved skills.
    """

    def session_start(self, task: str, agent_id: str) -> str:
        try:
            from l1.kernel.params.system import LOG_TRUNC_60, SKILL_CATALOG_HOOK_LIMIT
            from l1.kernel.skill import get_skill_manager
            sm = get_skill_manager()
            skills = sm.list(limit=SKILL_CATALOG_HOOK_LIMIT, sort_by="loaded_at")[:SKILL_CATALOG_HOOK_LIMIT]
            if skills:
                lines = ["\nAvailable skills (use_skill to invoke):"]
                for s in skills:
                    desc = (s.get("description", "") or "")[:LOG_TRUNC_60]
                    lines.append(f"  {s['name']}: {desc}")
                task += "\n".join(lines)
        except Exception as e:
            logger.debug("SkillCatalogHook: %s", e)
        return task


class CadenceHook(LifecycleHooks):
    """Edit-then-verify nudging — detects edits without follow-up checks."""

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
        unverified = [e for e in self._edited if e not in self._nudged]
        if not unverified:
            return None
        self._nudged.update(unverified)
        return ("Unverified edits detected. "
                "Run verification commands (build/test/lint) and "
                "use 'todowrite' with status='verified' when checks pass.")


class StatusReminderHook(LifecycleHooks):
    """Inject current date/time info per turn."""

    def pre_request(self, messages: list[dict], ctx: dict) -> list[dict]:
        import time
        ts = time.strftime("%Y-%m-%d %H:%M:%S %Z")
        reminder = {"role": "user", "content": f"[System time: {ts}]",
                     "synthetic": True}
        messages.append(reminder)
        return messages
