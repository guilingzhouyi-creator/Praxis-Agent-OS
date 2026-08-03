"""SubAgent task execution — lifecycle management for delegated tasks."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.params.agent import SUBAGENT_MAX_TOKENS, SUBAGENT_SESSION_TTL
from l1.kernel.params.system import LOG_TRUNC_100, LOG_TRUNC_2000

from .subagent_spec import SubAgentSpec

logger = logging.getLogger(__name__)


class SubAgentTask:
    """Single sub-agent task instance with AgentLoop multi-step execution + result delivery.

    Two execution modes:
      1. read_only=True  → engine.generate() (single LLM call, fast)
      2. read_only=False → AgentLoop.tool_use() (multi-step, tool calls)

    On completion, result is delivered to the parent Peer Agent via
    CellMessage mailbox (SUBAGENT_RESULT type). If the Peer Agent is
    busy, the message is queued in the Cell's mailbox (TTL-managed).
    """

    def __init__(self, task_id: str, spec: SubAgentSpec,
                 prompt: str, parent_agent_id: str = "",
                 context: dict | None = None,
                 cell=None,
                 territory: list[str] | None = None,
                 session_id: str = "",
                 ttl: float = SUBAGENT_SESSION_TTL):
        self.id = task_id
        self.spec = spec
        self.prompt = prompt
        self.parent_agent_id = parent_agent_id
        self.context = context or {}
        self.cell = cell
        self.territory = territory or []
        # ExploreCard: no territory restriction (read-only can go anywhere).
        # ExecuteCard: inherit parent Peer Agent's territory.
        if self.spec.read_only:
            self.territory = []
        self.session_id = session_id or task_id
        self.ttl = ttl
        self.status: str = "pending"
        self.result: dict = {}
        self.started_at: float = 0
        self.completed_at: float = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._cancelled = False

    def start(self) -> dict:
        with self._lock:
            self.status = "running"
            self.started_at = time.time()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return {"success": True, "task_id": self.id, "spec": self.spec.name}

    def _run(self) -> None:
        try:
            if self.spec.read_only:
                self._run_generate()
            else:
                self._run_agentloop()
            if self._cancelled:
                return
            post_results = self._run_post_actions()
            if post_results:
                with self._lock:
                    self.result["post_actions"] = post_results
            self._deliver_result()
        except Exception as e:
            with self._lock:
                self.status = "failed"
                self.completed_at = time.time()
                self.result = {"error": str(e)}

    _POST_ACTION_TYPES = frozenset({"scout"})

    def _run_post_actions(self) -> list[dict]:
        if not self.spec.post_actions or not self.cell:
            return []
        results = []
        for action in self.spec.post_actions:
            t = action.get("type", "")
            if t not in self._POST_ACTION_TYPES:
                continue
            try:
                r = self._exec_post_action(action)
                results.append(r)
            except Exception as e:
                results.append({"type": t, "error": str(e)})
        return results

    def _exec_post_action(self, action: dict) -> dict:
        t = action.get("type")
        prompt = action.get("prompt", "")
        if t == "scout":
            return self._exec_post_scout(prompt)
        return {"type": t, "error": f"unsupported: {t}"}

    def _exec_post_scout(self, prompt_template: str) -> dict:
        prompt = prompt_template.format(
            result=str(self.result)[:LOG_TRUNC_2000],
            answer=str(self.result.get("answer", ""))[:1000],
            task_id=self.id,
        )
        try:
            from ..agent.scout import get_pool
            pool = get_pool()
            session = pool.get(self.parent_agent_id or self.id)
            if session is None:
                return {"type": "scout", "error": "no scout available"}
            result = session.run(prompt)
            pool.put(session)
            return {"type": "scout", "result": str(result)[:LOG_TRUNC_2000]}
        except Exception as e:
            return {"type": "scout", "error": str(e)}

    def resolve_model_kwargs(self) -> dict:
        """Resolve model kwargs from spec's model_spec name + overrides."""
        try:
            from l3.services.model_service import get_service as _ms
            spec_name = self.spec.model_spec or "subagent"
            overrides = self.spec.model_config or {}
            return _ms().resolve_dict(spec_name, overrides=overrides)
        except Exception:
            return {}

    def _run_generate(self) -> None:
        """Fast path — single LLM call, no tools."""
        from l4.llm.llm import get_engine
        engine = get_engine()
        model_kwargs = self._resolve_model_kwargs()
        from l1.kernel.prompts import get_prompt as _gpr
        system = self.spec.system_prompt or _gpr(
            "subagent.fallback", "You are {name}. {description}"
        ).format(name=self.spec.name, description=self.spec.description)

        result = engine.generate(
            prompt=self.prompt,
            system=system,
            max_tokens=SUBAGENT_MAX_TOKENS,
            user_id=self.parent_agent_id or self.id,
            **model_kwargs,
        )

        with self._lock:
            if self._cancelled:
                return
            self.status = "completed"
            self.completed_at = time.time()
            self.result = {"answer": result.get("content", ""), "mode": "generate"}

    def _run_agentloop(self) -> None:
        """Multi-step path — full AgentLoop with tool_use()."""
        from l1.kernel.params.agent import (
            AGENT_LOOP_DEFAULT_STEPS,
            AGENT_LOOP_DEFAULT_TIMEOUT,
        )
        from l1.kernel.prompts import get_prompt as _gpr

        system = self.spec.system_prompt or _gpr(
            "subagent.fallback", "You are {name}. {description}"
        ).format(name=self.spec.name, description=self.spec.description)

        from .agent_loop import AgentLoop
        from .tool_system.tool_spec import get_tool

        loop = AgentLoop(
            task=self.prompt,
            agent_id=self.id,
            system=system,
            user_id=self.parent_agent_id or self.id,
            cell_id=self.cell.cell_id if self.cell else "",
        )

        for tool_name in self.spec.allowed_tools:
            spec = get_tool(tool_name)
            if spec is None:
                continue
            params = getattr(spec, "parameters", {}) or {}
            desc = getattr(spec, "description", "") or tool_name
            handler = _resolve_tool_handler(tool_name)
            parallel = getattr(spec, "parallel_safe", False) or tool_name in (
                "read_file", "grep_search", "list_dir",
            )
            loop.add_tool(tool_name, desc, params, handler, parallel_safe=parallel)

        model_kwargs = self._resolve_model_kwargs()
        result = loop.run(
            max_steps=self.spec.max_steps or AGENT_LOOP_DEFAULT_STEPS,
            timeout=self.spec.timeout or AGENT_LOOP_DEFAULT_TIMEOUT,
            **model_kwargs,
        )

        with self._lock:
            if self._cancelled:
                return
            self.status = "completed"
            self.completed_at = time.time()
            self.result = {
                "answer": result.get("answer", ""),
                "steps": result.get("steps", []),
                "tool_call_results": result.get("tool_call_results", []),
                "mode": "agentloop",
            }

    def _deliver_result(self) -> None:
        """Deliver result to parent Peer Agent via CellMessage mailbox."""
        if not self.cell or not self.parent_agent_id:
            return
        try:
            from l3.cell.components.cell_types import MessageType
            self.cell.send_message(
                sender=self.id,
                target=self.parent_agent_id,
                msg_type=MessageType.SUBAGENT_RESULT,
                payload={
                    "task_id": self.id,
                    "spec": self.spec.name,
                    "status": self.status,
                    "result": self.get_result(),
                },
            )
        except Exception as e:
            logger.warning("subagent %s: result delivery failed: %s", self.id, e)

    def cancel(self) -> dict:
        with self._lock:
            self._cancelled = True
            if self.status != "running":
                self.status = "cancelled"
                return {"success": True, "task_id": self.id, "status": "cancelled"}
            self.status = "cancelled"
        return {"success": True, "task_id": self.id, "status": "cancelled"}

    def get_result(self) -> dict:
        with self._lock:
            elapsed = 0
            if self.started_at > 0:
                elapsed = (self.completed_at or time.time()) - self.started_at
            return {
                "success": True,
                "task_id": self.id,
                "spec": self.spec.name,
                "status": self.status,
                "prompt": self.prompt[:LOG_TRUNC_100],
                "result": self.result,
                "elapsed_seconds": round(elapsed, 1),
                "started_at": self.started_at,
                "completed_at": self.completed_at,
            }


# ── Tool handler resolution cache ──

_HANDLER_CACHE: dict[str, Any] = {}


def _resolve_tool_handler(tool_name: str) -> Any:
    if tool_name in _HANDLER_CACHE:
        return _HANDLER_CACHE[tool_name]
    try:
        from ._term_handlers import _HANDLER_MAP
        handler = _HANDLER_MAP.get(tool_name)
        if handler:
            _HANDLER_CACHE[tool_name] = handler
            return handler
    except Exception:
        logger.debug("subagent_task: handler cache failed")
    def _generic(tool_name, args, agent_id):
        return {"success": True, "output": f"executed {tool_name}"}
    _HANDLER_CACHE[tool_name] = _generic
    return _generic
