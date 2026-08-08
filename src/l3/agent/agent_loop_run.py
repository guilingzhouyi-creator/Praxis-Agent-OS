"""AgentLoop run mixin — the tool-calling loop, finish funnel, and continuation.

Extracted from ``agent_loop.py`` (AgentLoop) to slim the class. ``run()``
is the orchestrator: it resolves the step budget, builds/reuses the cached
context, delegates the LLM turn and the steps-exhausted auto-continuation
to private helpers, and funnels every exit through ``_finish()``.
``AgentLoop`` inherits this mixin so runtime behavior is unchanged.
"""

from __future__ import annotations

import hashlib as _hl
import logging
import time
from concurrent.futures import as_completed
from typing import Any

from l1.kernel.params.agent import (
    AGENT_LOOP_CONTEXT_TB_LIMIT,
    AGENT_LOOP_DEFAULT_STEPS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    AGENT_LOOP_FUTURE_TIMEOUT,
    AGENT_LOOP_MAX_CONTENT,
    AGENT_LOOP_UNLIMITED_STEPS,
)
from l1.kernel.params.system import (
    HASH_TRUNC_SHORT,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    MEMORY_IMPORTANCE_DECISION,
    MEMORY_PROMOTION_THRESHOLD,
)
from l1.kernel.ports import get_port as _get_port
from l1.kernel.prompts import get_prompt

from .session_snapshot import STEPS_EXHAUSTED_NUDGE, TRUNCATION_RESUME_NUDGE

logger = logging.getLogger(__name__)


# Max accumulated content length across truncation, correction, and nudge appends
_AGENT_LOOP_MAX_CONTENT: int = AGENT_LOOP_MAX_CONTENT  # chars (~25K tokens)


class AgentLoopRunMixin:
    """Tool-calling loop orchestration, finish funnel, and continuation paths."""

    def run(
        self,
        max_steps: int = 0,
        timeout: float = AGENT_LOOP_DEFAULT_TIMEOUT,
        verifier: Any | None = None,
        model_config: dict | None = None,
    ) -> dict:
        """Run the tool-calling loop.

        Args:
            max_steps: If 0 (default), queries SettingsCenter for ``loop.max_steps``.
                       If > 0, overrides SettingsCenter value.
                       If < 0 (e.g. -1), runs with no step limit (unlimited mode).
            model_config: Per-call overrides for LLM config.
                Keys: provider, model, max_tokens, temperature,
                      reasoning_effort, thinking_budget
                None = use global LLM engine config.
        """
        max_steps = self._resolve_max_steps(max_steps)
        self._max_steps = max_steps
        t0 = time.time()
        side_times: dict[str, float] = {
            "compression": 0.0,  # pre-send context guard (stub_compact/compact)
            "parallel_read": 0.0,  # read-only tools parallel re-execution
            "continuation": 0.0,  # nudges / verifier fixes / steps-exhausted
            "llm_tools": 0.0,  # tool handler wall time inside LLM engine
        }
        self._loop_detector.reset()
        self._repeat_detector.reset()
        self._cadence.reset()

        engine = _get_port("llm")
        if self._cached_system:
            # continue_run() path: reuse cached system prompt and tools.
            # The identical system string enables LLM prompt caching across calls.
            system = self._cached_system
            wrapped_tools, read_only_tools = self._cached_tools
            model_kwargs = self._cached_model_kwargs.copy() if self._cached_model_kwargs else {}
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
        else:
            # First run: build fresh, cache for subsequent calls.
            system, wrapped_tools, read_only_tools, model_kwargs = self._build_run_context(
                max_steps, model_config, engine
            )
            system = self._inject_extra_context(system)
            self._cached_system = system
            self._cached_tools = (wrapped_tools, read_only_tools)
            self._cached_model_kwargs = dict(model_kwargs)
        deadline = time.time() + timeout if timeout > 0 else float("inf")

        ctx_window, _guard_finish = self._pre_send_compression_guard(system, engine, side_times, t0)
        if _guard_finish is not None:
            return _guard_finish

        # ── Main LLM turn: tool_use call + processing + nudges ──
        processed_results, all_passed, corrections, verifier_used, turns, result = self._run_llm_turn(
            engine=engine,
            system=system,
            wrapped_tools=wrapped_tools,
            read_only_tools=read_only_tools,
            model_kwargs=model_kwargs,
            max_steps=max_steps,
            ctx_window=ctx_window,
            side_times=side_times,
            deadline=deadline,
            verifier=verifier,
            t0=t0,
        )

        # ── Steps-exhausted auto-continuation ──
        all_passed, turns, processed_results = self._run_steps_exhausted(
            engine=engine,
            system=system,
            wrapped_tools=wrapped_tools,
            model_kwargs=model_kwargs,
            max_steps=max_steps,
            ctx_window=ctx_window,
            deadline=deadline,
            side_times=side_times,
            result=result,
            processed_results=processed_results,
            all_passed=all_passed,
            corrections=corrections,
            verifier_used=verifier_used,
            turns=turns,
            t0=t0,
        )

        return self._finish(
            {
                "success": all_passed,
                "answer": result.get("content", ""),
                "steps": [
                    {"step": i, "action": tc.get("name", "?"), "result": str(tc)[:LOG_TRUNC_200]}
                    for i, tc in enumerate(processed_results)
                ],
                "reasoning_trail": result.get("reasoning_trail", []) or [],
                "reasoning_tokens": result.get("reasoning_tokens", 0) or 0,
                "side_execution": {k: round(v, 3) for k, v in side_times.items()},
                "verifier_used": verifier_used,
                "corrections": corrections,
                "loop_stopped": any(s.get("_loop_stopped") for s in processed_results if isinstance(s, dict)),
                "awaiting_input": any(isinstance(s, dict) and s.get("_awaiting_input") for s in processed_results),
            },
            t0=t0,
            turns=turns,
            corrections=corrections,
            processed_count=len(processed_results),
        )

    # ── LLM turn ──────────────────────────────────────────────────────────

    def _run_llm_turn(
        self,
        *,
        engine: Any,
        system: str,
        wrapped_tools: list,
        read_only_tools: list,
        model_kwargs: dict,
        max_steps: int,
        ctx_window: int,
        side_times: dict[str, float],
        deadline: float,
        verifier: Any | None,
        t0: float,
    ) -> tuple[list, bool, int, bool, int, dict]:
        """Execute one LLM tool_use call and process its results.

        Handles truncation continuation, post-tool stub compression, the
        guard-mixin tool-result processing, continuation nudges, parallel
        read-only replay, and the consistency check. Returns the processed
        results and aggregate counters for the run orchestrator.
        """
        from l3.error_bus import error_boundary

        with error_boundary("LLM tool_use failed", component="services", agent_id=self.agent_id):
            result = engine.tool_use(
                prompt=self.task,
                tools=wrapped_tools,
                system=system,
                max_turns=max_steps,
                user_id=self._user_id,
                context_trail=self._context_trail,
                **model_kwargs,
            )
        side_times["llm_tools"] = float(result.get("tools_elapsed", 0) or 0)
        if not result:
            return (
                [],
                False,
                0,
                False,
                0,
                {
                    "success": False,
                    "answer": "",
                    "steps": [],
                    "error": "LLM call failed",
                    "verifier_used": False,
                    "corrections": 0,
                    "loop_stopped": False,
                },
            )

        self._context_trail = result.get("context_trail")
        # Persist context_trail to snapshot so it survives agent restart.
        # Only save when we have actual messages and an agent_id to key on.
        if self._context_trail and self._user_id:
            try:
                from .agent_persist import save_snapshot

                save_snapshot(
                    self._user_id,
                    {
                        "context_trail": self._context_trail,
                    },
                )
            except Exception as e:
                logger.warning("agent_loop: snapshot save failed: %s", e)
        turns = result.get("turns", 1)
        tool_results = result.get("tool_call_results", []) or []

        # ── Truncation continuation ──
        if result.get("finish_reason") == "length":
            try:
                cont = engine.generate(
                    prompt=TRUNCATION_RESUME_NUDGE, system=system, user_id=self._user_id, **model_kwargs
                )
                result["content"] = (result.get("content", "") + "\n" + cont.get("content", ""))[
                    :_AGENT_LOOP_MAX_CONTENT
                ]
                turns += 1
            except Exception as e:
                logger.warning("truncation continuation failed: %s", e)

        # ── Post-tool stub compression guard ──
        try:
            tb = sum(len(str(tc)) for tc in tool_results)
            if tb > AGENT_LOOP_CONTEXT_TB_LIMIT and ctx_window > 0:
                from l3.memory.memory import get_memory

                get_memory().stub_compact(self.agent_id)
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)

        # ── Process each tool result with loop detection + retry + cadence ──
        continuation_nudge: str | None = None
        processed_results, all_passed, corrections, verifier_used = self._process_tool_results(
            tool_results, result, system, engine, model_kwargs, deadline, verifier, side_times
        )

        # ── Continuation nudges ──
        if self._todo._continuation_nudge and self._todo.has_open_items() and processed_results:
            continuation_nudge = get_prompt("agent_loop.continuation_nudge", "")
        elif continuation_nudge is None and self._cadence.nudge():
            continuation_nudge = self._cadence.nudge()

        if continuation_nudge:
            _t_nudge = time.time()
            try:
                cont = engine.generate(prompt=continuation_nudge, system=system, user_id=self._user_id, **model_kwargs)
                result["content"] = (result.get("content", "") + "\n" + cont.get("content", ""))[
                    :_AGENT_LOOP_MAX_CONTENT
                ]
            except Exception as e:
                logger.warning("agent_loop continuation nudge failed: %s", e)
            finally:
                side_times["continuation"] += time.time() - _t_nudge

        # ── Parallel read-only tool execution ──
        if read_only_tools and processed_results:
            _t_pr = time.time()
            try:
                fs = {}
                for rt in read_only_tools:
                    for sr in processed_results:
                        if isinstance(sr, dict) and sr.get("name") == rt.name:
                            fs[self._parallel_executor.submit(rt.handler, sr.get("args", {}), self.agent_id)] = rt.name
                for f in as_completed(fs):
                    f.result(timeout=AGENT_LOOP_FUTURE_TIMEOUT)
            except Exception as e:
                logger.warning("parallel execution failed: %s", e)
            finally:
                side_times["parallel_read"] += time.time() - _t_pr

        # ── Consistency check ──
        if verifier is not None and len(processed_results) >= 2:
            cc = verifier.consistency_check(processed_results, self.task)
            if not cc.get("consistent"):
                logger.info("consistency issue: %s", cc.get("conflicts", []))

        return processed_results, all_passed, corrections, verifier_used, turns, result

    # ── Steps-exhausted continuation ──────────────────────────────────────

    def _run_steps_exhausted(
        self,
        *,
        engine: Any,
        system: str,
        wrapped_tools: list,
        model_kwargs: dict,
        max_steps: int,
        ctx_window: int,
        deadline: float,
        side_times: dict[str, float],
        result: dict,
        processed_results: list,
        all_passed: bool,
        corrections: int,
        verifier_used: bool,
        turns: int,
        t0: float,
    ) -> tuple[bool, int, list]:
        """Auto-continue after steps are exhausted: compress, nudge, re-run.

        Bounded by ``loop.max_attempts`` (SettingsCenter, default 3).
        Early-returns the terminal result dict (via ``_finish``) when the
        continuation nudge is disabled; otherwise mutates and returns the
        aggregate state for the run orchestrator.
        """
        if (
            not all_passed
            and max_steps < AGENT_LOOP_UNLIMITED_STEPS
            and result.get("finish_reason") in ("max_turns", "stop")
        ):
            from l3.error_bus import error_boundary

            with error_boundary("steps-exhausted continuation failed", component="agent", agent_id=self.agent_id):
                from l3.config.settings_center import get_center as _get_c

                _sc = _get_c()
                if not _sc.get("loop.continuation_nudge", True):
                    self._finish(
                        {
                            "success": all_passed,
                            "answer": result.get("content", ""),
                            "steps": [
                                {"step": i, "action": tc.get("name", "?"), "result": str(tc)[:LOG_TRUNC_200]}
                                for i, tc in enumerate(processed_results)
                            ],
                            "verifier_used": verifier_used,
                            "corrections": corrections,
                            "loop_stopped": any(
                                s.get("_loop_stopped") for s in processed_results if isinstance(s, dict)
                            ),
                        },
                        t0=t0,
                        turns=turns,
                        corrections=corrections,
                        processed_count=len(processed_results),
                    )
                    return all_passed, turns, processed_results
                _max_attempts = _sc.get_int("loop.max_attempts", 3)
                for _attempt in range(_max_attempts):
                    _t_se = time.time()
                    # 1. Compress context
                    try:
                        from .session_snapshot import should_compress as _sc2

                        if ctx_window > 0 and _sc2(_AGENT_LOOP_MAX_CONTENT, ctx_window):
                            from l3.memory.memory import get_memory

                            get_memory().stub_compact(self.agent_id)
                    except (ImportError, AttributeError):
                        logger.debug("agent_loop: steps-exhausted compress failed")
                    # 2. Save context trail snapshot
                    if self._context_trail and self._user_id:
                        try:
                            from .agent_persist import save_snapshot

                            save_snapshot(
                                self._user_id,
                                {
                                    "context_trail": self._context_trail,
                                },
                            )
                        except (ImportError, AttributeError, OSError):
                            logger.debug("agent_loop: steps-exhausted snapshot failed")
                    # 3. Issue steps-exhausted nudge + continue
                    nudge_r = engine.generate(
                        prompt=STEPS_EXHAUSTED_NUDGE, system=system, user_id=self._user_id, **model_kwargs
                    )
                    result["content"] = (result.get("content", "") + "\n" + nudge_r.get("content", ""))[
                        :_AGENT_LOOP_MAX_CONTENT
                    ]
                    # 4. Run next tool-use batch
                    nr = engine.tool_use(
                        prompt=self.task,
                        tools=wrapped_tools,
                        system=system,
                        max_turns=max_steps,
                        user_id=self._user_id,
                        context_trail=self._context_trail,
                        **model_kwargs,
                    )
                    side_times["continuation"] += time.time() - _t_se
                    if not nr:
                        break
                    self._context_trail = nr.get("context_trail")
                    nr_turns = nr.get("turns", 0)
                    turns += nr_turns
                    # Merge new tool results
                    nr_tools = nr.get("tool_call_results", [])
                    for _sr in nr_tools:
                        processed_results.append(
                            {
                                "step": len(processed_results),
                                "action": (_sr.get("name", "?") if isinstance(_sr, dict) else "?"),
                                "result": str(_sr)[:LOG_TRUNC_200],
                            }
                        )
                    # 5. Check completion
                    nr_finish = nr.get("finish_reason", "")
                    if nr_finish in ("stop", "end_turn"):
                        all_passed = True
                        break
                    if time.time() > deadline:
                        break

        return all_passed, turns, processed_results

    # ── Finish funnel ─────────────────────────────────────────────────────

    def _finish(
        self, result: dict, *, t0: float, turns: int = 0, corrections: int = 0, processed_count: int = 0
    ) -> dict:
        """Centralized terminal funnel — OpenCode-style.

        Called EXACTLY ONCE by every return path in run().
        Guarantees counter recording, cadence cleanup, and logging.
        Also injects a summary into the Cell's L2 cache for cross-agent sharing.
        """
        elapsed = time.time() - t0
        try:
            from l3.services.counter import get_counter

            get_counter().record_loop(
                agent_id=self._user_id,
                turns=turns + corrections,
                steps=processed_count,
                elapsed=elapsed,
                side=result.get("side_execution"),
            )
        except Exception as e:
            logger.warning("services/agent_loop: %s", e)
        try:
            from l3.services.stats_center import MetricPoint as _Mp3
            from l3.services.stats_center import get_center as _sc3

            for _k, _v in (result.get("side_execution") or {}).items():
                if _v:
                    _sc3().ingest(
                        _Mp3(
                            name=f"agent.loop.side.{_k}",
                            value=float(_v),
                            tags={"agent": self.agent_id},
                            timestamp=time.time(),
                            metric_type="gauge",
                        )
                    )
        except Exception:
            logger.debug("agent_loop: side timing stats failed")
        side = result.get("side_execution") or {}
        if side:
            try:
                from l3.bus.monitor_bus import MonitorEvent as _ME3  # noqa: N814
                from l3.bus.monitor_bus import get_bus as _MB3

                _MB3().emit(
                    _ME3(
                        type="stats.loop.side",
                        source="agent_loop",
                        severity="info",
                        message=f"{self.agent_id} side execution: {side}",
                        agent_id=self.agent_id,
                        cell_id=self._cell_id,
                        data={"side": side, "elapsed": round(elapsed, 3)},
                    )
                )
            except Exception:
                logger.debug("agent_loop: side timing monitor emit failed")
        self._todo._persist()
        # ── AutoTestGate: background test regression on card completion ──
        # Spawned when the loop left unverified edits and async mode is on.
        # Runs after cadence state is captured but before it is reset.
        try:
            from l3.tool_system.auto_test import maybe_trigger

            _unverified = self._cadence.unverified_edits()
            _card_id = getattr(self, "_last_card_id", "") or ""
            maybe_trigger(self.agent_id, self._cell_id, self.task, _unverified, card_id=_card_id)
        except Exception as e:
            logger.debug("agent_loop: auto_test trigger failed: %s", e)
        self._cadence.reset()

        # ── Cell L2 cache injection ──
        if self._cell_id:
            try:
                from l3.cell import get_cell as _get_cell

                cell = _get_cell(self._cell_id)
                answer = result.get("answer", "")
                # Use fingerprint of full task text for key uniqueness
                task_hash = _hl.sha256(self.task.encode()).hexdigest()[:HASH_TRUNC_SHORT]
                if result.get("success") and answer:
                    summary = answer.strip()[:LOG_TRUNC_200]
                    key = f"agent:{self.agent_id}:{task_hash}:r{self._run_count}"
                    cell.cache.inject(
                        key=key,
                        value=answer,
                        summary=summary,
                        agent_id=self.agent_id,
                        entry_type="decision",
                        importance=MEMORY_PROMOTION_THRESHOLD,
                    )
                elif not result.get("success") and result.get("error"):
                    error = result["error"][:LOG_TRUNC_200]
                    key = f"fail:{self.agent_id}:{task_hash}:r{self._run_count}"
                    cell.cache.inject(
                        key=key,
                        value=result.get("error", ""),
                        summary=f"FAIL [{self.agent_id}]: {error}",
                        agent_id=self.agent_id,
                        entry_type="failure",
                        importance=MEMORY_IMPORTANCE_DECISION,
                    )
            except Exception as e:
                logger.debug("cell cache inject: %s", e)

        # ── Snapshot hook ──
        try:
            from l3.agent.agent_persist import append_transcript

            record = {
                "task": self.task[:LOG_TRUNC_100],
                "success": result.get("success", False),
                "steps": result.get("total_steps", 0),
                "elapsed": round(elapsed, 2),
                "summary": str(result.get("answer", ""))[:LOG_TRUNC_200],
            }
            append_transcript(self._user_id, record)
        except Exception as e:
            logger.debug("persist append: %s", e)

        result["total_elapsed"] = round(elapsed, 2)
        result["total_steps"] = turns + corrections

        # ── Lifecycle hook chain: turn_complete (always) + on_error (on failure) ──
        try:
            from l3.services.hook import get_hook_chain as _get_hc

            _get_hc().turn_complete(result, elapsed)
            if not result.get("success"):
                _get_hc().on_error(result.get("error", "agent loop failed"))
        except Exception as e:
            logger.debug("agent_loop: hook chain emit failed: %s", e)

        return result

    # ── Continuation / lifecycle helpers ──────────────────────────────────

    def continue_run(self, task: str, timeout: float | None = None, model_config: dict | None = None) -> dict:
        """Continue the AgentLoop with a new task, preserving the existing system prompt.

        Used by persistent AgentLoop mode (AgentTerminal._persistent_loop).
        The system prompt, tools, and constitution context are reused from
        the initial ``run()`` call.

        Note: this does NOT share LLM conversation context between calls.
        Each ``continue_run()`` issues a fresh ``engine.tool_use()`` call.
        For true conversational continuity across cards, enable memory recall
        via ``memory.build_context()`` in the system prompt.
        """
        self.task = task
        return self.run(
            max_steps=0,
            timeout=timeout or AGENT_LOOP_DEFAULT_TIMEOUT,
            model_config=model_config,
        )

    def update_card_context(self, tags: list[str] | None = None, nature: str = "") -> None:
        """Refresh card-derived context for a persistent loop between cards.

        The persistent AgentLoop is reused across cards; skill retrieval
        must re-bias when the next card has a different nature/domain.
        """
        if tags:
            self.set_card_tags(tags)
        if nature:
            self._card_nature = nature

    def _resolve_max_steps(self, max_steps: int) -> int:
        """Resolve the effective step limit: SettingsCenter >= caller override > default."""
        if max_steps == 0:
            try:
                from l3.config.settings_center import get_center

                max_steps = get_center().get("loop.max_steps", AGENT_LOOP_DEFAULT_STEPS)
            except (ImportError, KeyError):
                max_steps = AGENT_LOOP_DEFAULT_STEPS
        # 0 or negative → unlimited mode (use a large sentinel for LLM max_turns)
        if max_steps <= 0:
            max_steps = AGENT_LOOP_UNLIMITED_STEPS
        return max_steps
