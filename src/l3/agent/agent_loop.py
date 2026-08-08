"""AgentLoop — LLM tool calling with loop detection, retry, and parallel tools.

Architecture:
  AgentLoop reads a Card, calls LLM in a loop, executes tools returned
  by the LLM, and verifies results.  The loop terminates when the goal
  is achieved, a max step count is reached, or a fatal error occurs.

Flow per turn:
  1. Build prompt (system + context + history + tool definitions)
  2. Call LLM (with tool-use / tool_choice)
  3. Parse tool calls from response
  4. Execute each tool (parallel via ThreadPoolExecutor)
  5. Collect results → append to conversation
  6. Self-verification check (verifier.py)
  7. If not done → goto 1

Loop detection (loop_detectors.py):
  - Stagnation: same action repeated without progress
  - Oscillation: A→B→A→B pattern
  - Diminishing returns: score not improving

Integration:
  - Card → AgentLoop → tools → results → CardRegistry
  - AgentLoop → Verifier (self-check) → correction → AgentLoop
  - AgentLoop → Review (peer-review) → feedback → AgentLoop

This module keeps the class core (state, tool registration, result folding,
handler wrapping); domain logic lives in sibling mixins: guard
(agent_loop_guard.py), context (agent_loop_context.py), and run
(agent_loop_run.py).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from l1.kernel.params.agent import (
    AGENT_LOOP_MAX_WORKERS,
    LOOP_FOLD_LIST_PREVIEW,
    LOOP_FOLD_LIST_TRUNCATION,
    R4_CARD_SKILL_SIGNAL_MAX,
    R4_CARD_TAG_MAX,
)
from l1.kernel.params.kernel import RING_1
from l1.kernel.params.system import (
    CONTEXT_TRAIL_TRUNC,
    LOG_TRUNC_200,
    LOG_TRUNC_500,
)
from l3.scheduler.loop_detectors import CoarseRepeatDetector, ToolLoopDetector
from l3.services.todo_tracker import TodoTracker
from l3.tool_system.tool_pipeline import get_pipeline
from l3.tool_system.tool_spec import ParamSpec, ToolSpec

from .agent_loop_context import AgentLoopContextMixin
from .agent_loop_guard import AgentLoopGuardMixin
from .agent_loop_run import AgentLoopRunMixin
from .verify_cadence import VerifyCadence

logger = logging.getLogger(__name__)


class AgentLoop(AgentLoopGuardMixin, AgentLoopContextMixin, AgentLoopRunMixin):
    """Tool-calling loop with loop detection, retry, and parallel tools.

    Usage:
      loop = AgentLoop(task="Read src/main.py and summarize")
      loop.add_tool("read_file", ...)
      result = loop.run(max_steps=AGENT_LOOP_DEFAULT_STEPS)
    """

    def __init__(
        self,
        task: str,
        agent_id: str = "",
        system: str = "",
        user_id: str = "",
        role: str = "",
        prompt_key: str = "",
        cell_id: str = "",
        todo_path: str = "",
    ):
        self.task = task
        self.agent_id = agent_id
        self._system = system
        self._role = role
        self._prompt_key = prompt_key
        self._user_id = user_id or agent_id
        self._cell_id = cell_id
        self._tools: list[ToolSpec] = []
        self._loop_detector = ToolLoopDetector(cell_id=cell_id, agent_id=agent_id)
        self._repeat_detector = CoarseRepeatDetector(cell_id=cell_id, agent_id=agent_id)
        self._todo = TodoTracker(state_path=todo_path)
        self._cadence = VerifyCadence()
        self._chat_params_hooks: list[Callable] = []
        self._run_count = 0
        self._context_trail: list[dict] | None = None
        # Cached state for continue_run() — built once on first run(), reused thereafter.
        # Maintaining identical system prompt + tools across calls enables LLM
        # provider prompt caching (Anthropic/DeepSeek) and avoids redundant work.
        self._cached_system: str = ""
        self._cached_tools: tuple[list, list] = ([], [])
        self._cached_model_kwargs: dict | None = None
        self._pmu: Any = None
        # Card-derived context tags (nature/domain of the driving card). These
        # bias skill retrieval so different card types hit different skills.
        self._card_tags: list[str] = []
        self._gate_scope: str = ""
        self._card_nature: str = ""
        # Skills used (use_skill) or injected during the current card's
        # execution — the preference signal for DPO-style rule weighting
        # (card success/failure is attributed to these skills downstream).
        self._card_skills_used: set[str] = set()
        # Persistent thread pool for parallel read-only tool execution
        # (avoids creating/destroying ThreadPoolExecutor on every loop iteration)
        self._parallel_executor = ThreadPoolExecutor(
            max_workers=AGENT_LOOP_MAX_WORKERS,
            thread_name_prefix=f"parallel-{agent_id}",
        )

    def set_pmu(self, pmu: Any) -> None:
        """Attach a Performance Monitoring Unit for counter tracking."""
        self._pmu = pmu

    def set_card_tags(self, tags: list[str]) -> None:
        """Set the card-derived context tags that bias skill retrieval."""
        if tags:
            self._card_tags = [t for t in tags if isinstance(t, str) and t][:R4_CARD_TAG_MAX]

    def register_chat_params_hook(self, hook: Callable) -> None:
        """Register a hook that modifies LLM call parameters.

        Hook signature: (task: str, agent_id: str, model_kwargs: dict) -> dict
        Receives current model_kwargs and returns updated dict.
        Called before every engine.tool_use() call in run().
        """
        if hook not in self._chat_params_hooks:
            self._chat_params_hooks.append(hook)

    def add_tool(
        self, name: str, description: str, params: dict[str, str], executor: Any, parallel_safe: bool = False
    ) -> None:
        """Register a tool. parallel_safe=True allows concurrent execution (read-only)."""
        param_specs = [ParamSpec(name=pn, type=pt, required=True, description=pn) for pn, pt in params.items()]
        self._tools.append(
            ToolSpec(
                name=name,
                description=description,
                category="",
                ring=RING_1,
                danger=0,
                parameters=param_specs,
                handler=executor,
                parallel_safe=parallel_safe,
            )
        )

    def add_tool_from_spec(self, spec: Any, handler: Any = None, parallel_safe: bool | None = None) -> None:
        """Register a tool marshalled from an existing spec.

        Shared marshalling point for the Cell SubAgentPool and L3A
        subagent runners: name/description/parameters/parallel_safe come
        from ``spec`` (a ToolSpec, or any object exposing those) and the
        executor is ``handler`` when given, else ``spec.handler``.

        Args:
            spec: ToolSpec (or compatible) to register.
            handler: callable (args, agent_id) -> dict; overrides spec.handler.
            parallel_safe: explicit override; defaults to spec.parallel_safe.
        """
        raw = getattr(spec, "parameters", None)
        params: dict[str, str] = {}
        if isinstance(raw, dict):
            for pn, pv in raw.items():
                params[pn] = pv.get("type", "string") if isinstance(pv, dict) else "string"
        elif isinstance(raw, (list, tuple)):
            for p in raw:
                pn = getattr(p, "name", None)
                if pn:
                    params[pn] = str(getattr(p, "type", "") or "string")
        is_parallel = bool(getattr(spec, "parallel_safe", False)) if parallel_safe is None else parallel_safe
        executor = handler if handler is not None else getattr(spec, "handler", None)
        self.add_tool(
            name=spec.name,
            description=getattr(spec, "description", "") or spec.name,
            params=params,
            executor=executor,
            parallel_safe=is_parallel,
        )

    def _truncate_trail(self, keep: int = CONTEXT_TRAIL_TRUNC) -> int:
        """Fold older context_trail messages into a single summary line.

        Keeps the most recent `keep` messages; older ones become one
        system summary message. Returns number of messages removed.
        """
        if not self._context_trail or len(self._context_trail) <= keep:
            return 0
        old = self._context_trail[:-keep]
        recent = self._context_trail[-keep:]
        removed = len(old)
        user_lines = [m.get("content", "")[:LOG_TRUNC_200] for m in old if m.get("role") == "user"]
        summary = (
            "[HISTORY TRUNCATED] earlier context: "
            + "; ".join(user_lines[:5])
            + (f" (+{len(user_lines) - 5} more)" if len(user_lines) > 5 else "")
        )
        self._context_trail = [{"role": "system", "content": summary}] + recent
        logger.debug("agent_loop: trail truncated, removed %d msgs", removed)
        return removed

    def _fold_result(self, result: dict, max_chars: int = LOG_TRUNC_500) -> dict:
        """Head+tail truncation: keeps both ends, elides middle.

        AtomCode-style: when content exceeds max_chars, the first half and
        last half are preserved with a truncation marker. This is better than
        head-only truncation because tool output's signal often lives at both ends.
        """
        folded: dict[str, Any] = {}
        truncated = False
        for k, v in result.items():
            if isinstance(v, str) and len(v) > max_chars:
                half = max_chars // 2
                head = v[:half]
                tail = v[-half:] if half > 0 else ""
                folded[k] = f"{head}\n...[truncated: {len(v) - max_chars} chars elided]...\n{tail}"
                folded[k + "_truncated"] = len(v) - max_chars
                truncated = True
            elif isinstance(v, list) and len(v) > LOOP_FOLD_LIST_TRUNCATION:
                folded[k] = v[:LOOP_FOLD_LIST_PREVIEW]
                folded[k + "_total"] = len(v)
                truncated = True
            elif isinstance(v, dict):
                folded[k] = self._fold_result(v, max_chars)
            else:
                folded[k] = v
        if truncated:
            folded["_truncation_note"] = (
                "Output truncated (head+tail preserved). "
                "Use the tool with limit/offset parameters to get specific portions."
            )
        return folded

    def _wrap_handler(self, fn: Any) -> Any:
        """Wrap a tool handler with the tool pipeline (clearance, rate, alloc gates)."""
        pipeline = get_pipeline()

        def wrapped(args, agent):
            """Execute the handler through the pipeline and log failures."""
            # Card→skill signal: a use_skill invocation names the skill in
            # args; attribute it to the current card's preference set.
            try:
                _tool = fn.__name__ if hasattr(fn, "__name__") else ""
                if _tool == "use_skill":
                    _sk = args.get("name", "") if isinstance(args, dict) else ""
                    _used = getattr(self, "_card_skills_used", None)
                    if _sk and _used is not None and len(_used) < R4_CARD_SKILL_SIGNAL_MAX:
                        _used.add(_sk)
            except Exception:
                pass
            # Forward the driving card nature into the tool args so tools
            # that gate on it (e.g. use_skill's offensive-posture check) can
            # see it — the LLM-generated args never carry this internal field.
            if isinstance(args, dict) and getattr(self, "_card_nature", "") and not args.get("_card_nature"):
                args["_card_nature"] = self._card_nature
            pr = pipeline.execute(
                tool_name=fn.__name__ if hasattr(fn, "__name__") else "unknown",
                agent_id=self.agent_id,
                args=args,
                domain=getattr(self, "_gate_scope", ""),
                nature=getattr(self, "_card_nature", ""),
                _executor=lambda name, a, aid: fn(a, aid),
            )
            if not pr.get("success"):
                return {
                    "success": False,
                    "error": pr.get("error", "pipeline rejected"),
                    "gate_steps": pr.get("steps", []),
                }
            result = pr.get("result", {})
            if isinstance(result, dict):
                result = self._fold_result(result)
            return result

        wrapped.__name__ = fn.__name__ if hasattr(fn, "__name__") else "wrapped"
        return wrapped
