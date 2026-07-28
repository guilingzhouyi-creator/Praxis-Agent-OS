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
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from l1.kernel.params.system import (
    HASH_TRUNC_SHORT,
    LOG_TRUNC_40,
    LOG_TRUNC_100,
    LOG_TRUNC_120,
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    LOG_TRUNC_500,
    CONTEXT_PRESSURE_WARN,
    CONTEXT_PRESSURE_MEDIUM,
    CONTEXT_PRESSURE_CRITICAL,
    CONTEXT_BUILD_MAX_TOKENS,
    CONTEXT_BUILD_MIN_TOKENS,
)
from l1.kernel.params.agent import (
    AGENT_LOOP_DEFAULT_STEPS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    AGENT_LOOP_FUTURE_TIMEOUT,
    AGENT_LOOP_MAX_WORKERS,
    AGENT_LOOP_MAX_CONTENT,
)
from l1.kernel.params.kernel import RING_1
from l1.kernel.prompts import get_prompt

from l4.llm.llm import get_engine
from l3.scheduler.loop_detectors import CoarseRepeatDetector, ToolLoopDetector
from .session_snapshot import TRUNCATION_RESUME_NUDGE, should_compress
from l3.services.todo_tracker import TodoTracker
from l3.tool_system.tool_pipeline import get_pipeline
from l3.tool_system.tool_spec import ParamSpec, ToolSpec
from .verify_cadence import VerifyCadence

logger = logging.getLogger(__name__)

# Max accumulated content length across truncation, correction, and nudge appends
_AGENT_LOOP_MAX_CONTENT: int = AGENT_LOOP_MAX_CONTENT  # chars (~25K tokens)


# extracted to services/todo_tracker.py
# extracted to services/verify_cadence.py
class AgentLoop:
    """Tool-calling loop with loop detection, retry, and parallel tools.

    Usage:
      loop = AgentLoop(task="Read src/main.py and summarize")
      loop.add_tool("read_file", ...)
      result = loop.run(max_steps=AGENT_LOOP_DEFAULT_STEPS)
    """

    def __init__(self, task: str, agent_id: str = "", system: str = "",
                 user_id: str = "", role: str = "", prompt_key: str = "",
                 cell_id: str = ""):
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
        self._todo = TodoTracker()
        self._cadence = VerifyCadence()
        self._chat_params_hooks: list[Callable] = []
        self._run_count = 0
        self._pmu: Any = None

    def set_pmu(self, pmu: Any) -> None:
        """Attach a Performance Monitoring Unit for counter tracking."""
        self._pmu = pmu

    def _build_run_context(self, max_steps: int, model_config: dict | None, engine: Any) -> tuple[str, list, list, dict]:
        """Build system prompt, wrap tools, and prepare model kwargs."""
        model_kwargs: dict = {}
        if model_config:
            for key in ("model", "max_tokens", "temperature",
                        "reasoning_effort", "thinking_budget"):
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
        if vc:
            system = (system + "\n\n" + vc) if system else vc
        if todo_reminder:
            system = (system + "\n\n" + todo_reminder) if system else todo_reminder

        try:
            from l1.kernel.constitution import get_constitution
            const_summary = get_constitution().summary(for_agent=self.agent_id)
            system = (system + "\n\n" + const_summary) if system else const_summary
        except Exception:
            pass

        wrapped_tools = []
        read_only_tools = []
        for t in self._tools:
            wrapped = ToolSpec(
                name=t.name, description=t.description, category=t.category,
                ring=t.ring, danger=t.danger,
                parameters=t.parameters, handler=self._wrap_handler(t.handler),
                parallel_safe=t.parallel_safe,
            )
            wrapped_tools.append(wrapped)
            if t.parallel_safe:
                read_only_tools.append(wrapped)
        return system, wrapped_tools, read_only_tools, model_kwargs

    def _inject_extra_context(self, system: str) -> str:
        """Inject R4 lean cases, evolved skills, and cross-cell rules into system prompt."""
        try:
            from .memory.r4_agent import get_r4_agent
            r4 = get_r4_agent()
            lean = r4.get_lean_cases(agent_id=self.agent_id, limit=3)
            if lean:
                lines = "\n".join(f"  {i}. {lc}" for i, lc in enumerate(lean, 1))
                system += f"\n\n--- Known Failure Patterns ---\n{lines}\n---"
            evolved = r4.get_evolved_skills(agent_id=self.agent_id, limit=2)
            if evolved:
                for es in evolved:
                    system += f"\n\n### {es['name']}\n{es['description']}\n{es['prompt'][:LOG_TRUNC_300]}"
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)
        try:
            from .cell.peers.l3 import get_coordinator
            coord = get_coordinator()
            if getattr(coord, '_cross_cell_active', False):
                system += get_prompt("agent_loop.cross_cell_rules", "")
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)
        return system

    def register_chat_params_hook(self, hook: Callable) -> None:
        """Register a hook that modifies LLM call parameters.

        Hook signature: (task: str, agent_id: str, model_kwargs: dict) -> dict
        Receives current model_kwargs and returns updated dict.
        Called before every engine.tool_use() call in run().
        """
        if hook not in self._chat_params_hooks:
            self._chat_params_hooks.append(hook)

    def add_tool(self, name: str, description: str, params: dict[str, str],
                 executor: Any, parallel_safe: bool = False) -> None:
        """Register a tool. parallel_safe=True allows concurrent execution (read-only)."""
        param_specs = [ParamSpec(name=pn, type=pt, required=True, description=pn)
                       for pn, pt in params.items()]
        self._tools.append(ToolSpec(
            name=name, description=description, category="",
            ring=RING_1, danger=0,
            parameters=param_specs, handler=executor,
            parallel_safe=parallel_safe,
        ))

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
            self._tools.append(ToolSpec(
                name="todowrite",
                description="Update task list status. status: pending|in_progress|completed. Use 'add' for new items.",
                category="generic", ring=RING_1, danger=0,
                parameters=[
                    ParamSpec("content", "string", required=True, description="Task description"),
                    ParamSpec("status", "string", required=True,
                              description="pending|in_progress|completed|add"),
                ],
                handler=_todowrite_handler,
                parallel_safe=False,
            ))

    def _fold_result(self, result: dict, max_chars: int = LOG_TRUNC_500) -> dict:
        """Head+tail truncation: keeps both ends, elides middle.

        AtomCode-style: when content exceeds max_chars, the first half and
        last half are preserved with a truncation marker. This is better than
        head-only truncation because tool output's signal often lives at both ends.
        """
        folded = {}
        truncated = False
        for k, v in result.items():
            if isinstance(v, str) and len(v) > max_chars:
                half = max_chars // 2
                head = v[:half]
                tail = v[-half:] if half > 0 else ""
                folded[k] = f"{head}\n...[truncated: {len(v) - max_chars} chars elided]...\n{tail}"
                folded[k + "_truncated"] = len(v) - max_chars
                truncated = True
            elif isinstance(v, list) and len(v) > 20:
                folded[k] = v[:15]
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
            pr = pipeline.execute(
                tool_name=fn.__name__ if hasattr(fn, '__name__') else "unknown",
                agent_id=self.agent_id,
                args=args,
                _executor=lambda name, a, aid: fn(a, aid),
            )
            if not pr.get("success"):
                return {"success": False, "error": pr.get("error", "pipeline rejected"),
                        "gate_steps": pr.get("steps", [])}
            result = pr.get("result", {})
            if isinstance(result, dict):
                result = self._fold_result(result)
            return result

        wrapped.__name__ = fn.__name__ if hasattr(fn, '__name__') else "wrapped"
        return wrapped

    def _finish(self, result: dict, *, t0: float, turns: int = 0,
                 corrections: int = 0, processed_count: int = 0) -> dict:
        """Centralized terminal funnel — OpenCode-style.

        Called EXACTLY ONCE by every return path in run().
        Guarantees counter recording, cadence cleanup, and logging.
        Also injects a summary into the Cell's L2 cache for cross-agent sharing.
        """
        elapsed = time.time() - t0
        try:
            from .services.counter import get_counter
            get_counter().record_loop(
                agent_id=self._user_id,
                turns=turns + corrections,
                steps=processed_count,
                elapsed=elapsed,
            )
        except Exception as e:
            logger.warning("services/agent_loop: %s", e)
        self._todo._persist()
        self._cadence.reset()

        # ── Cell L2 cache injection ──
        if self._cell_id:
            try:
                from l3.cell import get_cell as _get_cell
                cell = _get_cell(self._cell_id)
                answer = result.get("answer", "")
                # Use fingerprint of full task text for key uniqueness
                import hashlib as _hl
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
                        importance=0.6,
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
                        importance=0.3,
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
        return result

    def continue_run(self, task: str, timeout: float | None = None,
                     model_config: dict | None = None) -> dict:
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
            max_steps=AGENT_LOOP_DEFAULT_STEPS,
            timeout=timeout or AGENT_LOOP_DEFAULT_TIMEOUT,
            model_config=model_config,
        )

    def run(self, max_steps: int = AGENT_LOOP_DEFAULT_STEPS, timeout: float = AGENT_LOOP_DEFAULT_TIMEOUT,
            verifier: Any | None = None,
            model_config: dict | None = None) -> dict:
        """Run the tool-calling loop.

        Args:
            model_config: Per-call overrides for LLM config.
                Keys: provider, model, max_tokens, temperature,
                      reasoning_effort, thinking_budget
                None = use global LLM engine config.
        """
        t0 = time.time()
        self._loop_detector.reset()
        self._repeat_detector.reset()
        self._cadence.reset()

        engine = get_engine()
        system, wrapped_tools, read_only_tools, model_kwargs = self._build_run_context(max_steps, model_config, engine)
        system = self._inject_extra_context(system)
        deadline = time.time() + timeout if timeout > 0 else float("inf")

        # ── Pre-send compression guard (three-level cascade with PMU + MonitorBus) ──
        ctx_window = 0
        mem = None
        try:
            ctx_window = engine.context_window(cell_id=self._cell_id, agent_id=self.agent_id)
        except Exception:
            pass
        entity = self.agent_id

        def _emit_memory_event(etype: str, data: dict) -> None:
            """Emit a memory event to the monitor bus for cross-Cell observability."""
            try:
                from l3.bus.monitor_bus import MonitorEvent as _ME, get_bus as _MB
                _MB().emit(_ME(type=etype, source="agent_loop", severity="info",
                               agent_id=self.agent_id, cell_id=self._cell_id, data=data))
            except Exception:
                pass
            try:
                from l3.bus.reference_channel import get_rc as _rc
                _rc().event("memory_compression", {**data, "type": etype,
                            "agent_id": self.agent_id, "cell_id": self._cell_id},
                            source="agent_loop", trace_id=getattr(self, '_last_card_id', ''))
            except Exception:
                pass

        if ctx_window > 0:
            est_tokens = len(self.task) // 4
            est_total = est_tokens + len(system) // 4 + CONTEXT_BUILD_MAX_TOKENS
            ratio = est_total / ctx_window

            if ratio >= CONTEXT_PRESSURE_CRITICAL:
                logger.error("context exhausted: ~%d/%d tokens — aborting", est_total, ctx_window)
                if self._pmu:
                    self._pmu.increment("memory.context.critical")
                _emit_memory_event("memory.pressure.critical", {"ratio": ratio, "est_total": est_total, "ctx_window": ctx_window})
                return self._finish({
                    "success": False, "answer": "",
                    "error": f"context window exhausted (~{est_total}/{ctx_window} tokens)",
                    "steps": [], "verifier_used": False, "corrections": 0, "loop_stopped": False,
                }, t0=t0)

            if ratio >= CONTEXT_PRESSURE_MEDIUM:
                try:
                    from .memory.memory import get_memory as _gm
                    mem = _gm()
                    cr = mem.compact(self.agent_id)
                    mem.forget_agent(self.agent_id, ring=1)
                    logger.info("pre-send L2 compact+forget_R1: ~%d/%d (%.0f%%)",
                                est_total, ctx_window, ratio * 100)
                    if self._pmu:
                        self._pmu.increment("memory.context.warnings")
                        self._pmu.increment("memory.compacts")
                        self._pmu.increment("memory.compact.merges", cr.get("merged", 0))
                        self._pmu.increment("memory.compact.saved_tokens", cr.get("saved_tokens", 0))
                    _emit_memory_event("memory.compact", {"ratio": ratio, "merges": cr.get("merged", 0), "saved_tokens": cr.get("saved_tokens", 0)})
                except Exception as e:
                    logger.warning("agent_loop L2 compact failed: %s", e)

            if ratio >= CONTEXT_PRESSURE_WARN:
                try:
                    if mem is None:
                        from .memory.memory import get_memory as _gm2
                        mem = _gm2()
                    sr = mem.stub_compact(self.agent_id)
                    logger.info("pre-send L1 stub_compact: ~%d/%d (%.0f%%)",
                                est_total, ctx_window, ratio * 100)
                    if self._pmu:
                        self._pmu.increment("memory.stub_compacts")
                        self._pmu.increment("memory.stub_compact.saved_bytes", sr.get("saved_bytes", 0))
                    _emit_memory_event("memory.stub_compact", {"ratio": ratio, "stubbed": sr.get("stubbed", 0), "saved_bytes": sr.get("saved_bytes", 0)})
                except Exception as e:
                    logger.warning("agent_loop L1 stub_compact failed: %s", e)

        # Fallback: when ctx_window is unknown (0), compress every 3 runs
        if ctx_window <= 0 and self._run_count > 0 and self._run_count % 3 == 0:
            try:
                from .memory.memory import get_memory
                sr = get_memory().stub_compact(self.agent_id)
                if self._pmu:
                    self._pmu.increment("memory.stub_compacts")
                    self._pmu.increment("memory.stub_compact.saved_bytes", sr.get("saved_bytes", 0))
            except Exception as e:
                logger.warning("agent_loop stub_compact fallback failed: %s", e)
        self._run_count += 1

        # ── Main LLM tool_use call ──
        from l3.error_bus import error_boundary
        with error_boundary("LLM tool_use failed", component="services", agent_id=self.agent_id):
            result = engine.tool_use(
                prompt=self.task, tools=wrapped_tools, system=system,
                max_turns=max_steps, user_id=self._user_id, **model_kwargs,
            )
        if not result:
            return self._finish({
                "success": False, "answer": "", "steps": [],
                "error": "LLM call failed",
                "verifier_used": False, "corrections": 0, "loop_stopped": False,
            }, t0=t0)

        turns = result.get("turns", 1)
        tool_results = result.get("tool_call_results", []) or []

        # ── Truncation continuation ──
        if result.get("finish_reason") == "length":
            try:
                cont = engine.generate(prompt=TRUNCATION_RESUME_NUDGE, system=system,
                                       user_id=self._user_id, **model_kwargs)
                result["content"] = (result.get("content", "") + "\n" + cont.get("content", ""))[:_AGENT_LOOP_MAX_CONTENT]
                turns += 1
            except Exception as e:
                logger.warning("truncation continuation failed: %s", e)

        # ── Post-tool stub compression guard ──
        try:
            tb = sum(len(str(tc)) for tc in tool_results)
            if tb > 50000 and ctx_window > 0:
                from .memory.memory import get_memory
                get_memory().stub_compact(self.agent_id)
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)

        # ── Process each tool result with loop detection + retry + cadence ──
        processed_results: list[dict] = []
        all_passed = True
        corrections = 0
        verifier_used = False
        continuation_nudge: str | None = None

        for step_result in tool_results:
            if time.time() > deadline:
                result["finish_reason"] = "timeout"
                break
            tool_name = step_result.get("name", "unknown") if isinstance(step_result, dict) else "?"

            if self._loop_detector.check(tool_name, step_result.get("args", {}), step_result) == "stop":
                step_result["_loop_stopped"] = True
                processed_results.append(step_result)
                all_passed = False
                break

            if self._repeat_detector.check(tool_name) == "stop":
                step_result["_loop_stopped"] = True
                processed_results.append(step_result)
                all_passed = False
                break

            # Cadence tracking (via ToolConfig)
            try:
                from .tool_system.tool_config import ToolConfig as _TC
                if tool_name in _TC.write_tool_names():
                    self._cadence.record_edit((step_result.get("args", {}) if isinstance(step_result, dict) else {}).get("path", ""))
                if tool_name in _TC.terminal_tool_names():
                    self._cadence.record_check((step_result.get("args", {}) if isinstance(step_result, dict) else {}).get("command", ""))
            except Exception as e:
                logger.warning("agent_loop cadence tracking failed: %s", e)

            # PMU: tool call counter
            if self._pmu:
                ring_label = "ring_1"
                from l1.kernel.params.kernel import RING_NUM_MAP as _RNM
                try:
                    ts = get_pipeline()._specs.get(tool_name) if hasattr(get_pipeline(), '_specs') else None
                    ts_r = getattr(ts, "ring", None) if ts else None
                    if ts_r:
                        ring_label = _RNM.get(ts_r, "ring_1")
                    self._pmu.increment(f"tools.executed.{ring_label}")
                except Exception:
                    self._pmu.increment("tools.executed.ring_1")
            # CellCounter: record tool call (success inferred from no error key)
            try:
                from .services.counter import get_counter as _gc
                _gc().record_tool(self.agent_id, tool_name,
                                  success="error" not in (step_result.get("result", {}) if isinstance(step_result, dict) else {}))
            except Exception:
                pass

            if verifier is not None:
                v = verifier.check(step_result, self.task)
                if not v.get("pass") and v.get("retry_allowed"):
                    corrections += 1
                    try:
                        fix = engine.generate(prompt=verifier.correction_prompt(self.task, [v.get("reason", "")]),
                                              system=system, user_id=self._user_id, **model_kwargs)
                        result["content"] = (result.get("content", "") + "\n" + fix.get("content", ""))[:_AGENT_LOOP_MAX_CONTENT]
                        verifier_used = True
                        step_result["_corrected"] = True
                        # Persist correction to Cell L2 cache
                        if self._cell_id and v.get("reason"):
                            try:
                                from l3.cell import get_cell as _get_cell
                                cell = _get_cell(self._cell_id)
                                cell.cache.inject(
                                    key=f"correct:{self.agent_id}:{tool_name}:{self.task[:LOG_TRUNC_40]}",
                                    value={"tool": tool_name, "error": v.get("reason", ""), "fix": fix.get("content", "")[:LOG_TRUNC_300]},
                                    summary=f"CORRECT [{self.agent_id}] {tool_name}: {v.get('reason', '')[:LOG_TRUNC_120]}",
                                    agent_id=self.agent_id,
                                    entry_type="correction",
                                    importance=0.5,
                                )
                            except Exception:
                                pass
                    except Exception as e:
                        logger.warning("agent_loop verifier correction failed: %s", e)

            processed_results.append(step_result)

        # ── Continuation nudges ──
        if self._todo._continuation_nudge and self._todo.has_open_items() and processed_results:
            continuation_nudge = get_prompt("agent_loop.continuation_nudge", "")
        elif continuation_nudge is None and self._cadence.nudge():
            continuation_nudge = self._cadence.nudge()

        if continuation_nudge:
            try:
                cont = engine.generate(prompt=continuation_nudge, system=system,
                                       user_id=self._user_id, **model_kwargs)
                result["content"] = (result.get("content", "") + "\n" + cont.get("content", ""))[:_AGENT_LOOP_MAX_CONTENT]
            except Exception as e:
                logger.warning("agent_loop continuation nudge failed: %s", e)

        # ── Parallel read-only tool execution ──
        if read_only_tools and processed_results:
            try:
                with ThreadPoolExecutor(max_workers=AGENT_LOOP_MAX_WORKERS) as executor:
                    fs = {}
                    for rt in read_only_tools:
                        for sr in processed_results:
                            if isinstance(sr, dict) and sr.get("name") == rt.name:
                                fs[executor.submit(rt.handler, sr.get("args", {}), self.agent_id)] = rt.name
                    for f in as_completed(fs):
                        f.result(timeout=AGENT_LOOP_FUTURE_TIMEOUT)
            except Exception as e:
                logger.warning("parallel execution failed: %s", e)

        # ── Consistency check ──
        if verifier is not None and len(processed_results) >= 2:
            cc = verifier.consistency_check(processed_results, self.task)
            if not cc.get("consistent"):
                logger.info("consistency issue: %s", cc.get("conflicts", []))

        return self._finish({
            "success": all_passed,
            "answer": result.get("content", ""),
            "steps": [{"step": i, "action": tc.get("name", "?"), "result": str(tc)[:LOG_TRUNC_200]}
                      for i, tc in enumerate(processed_results)],
            "verifier_used": verifier_used,
            "corrections": corrections,
            "loop_stopped": any(s.get("_loop_stopped") for s in processed_results if isinstance(s, dict)),
        }, t0=t0, turns=turns, corrections=corrections, processed_count=len(processed_results))
