"""Agent Runtime — wraps an Agent process with kernel primitives.

Each Agent runs as an independent process/shell.
This runtime manages its syscalls, locks, resources, constitution, and memory refeed.

Flow:
  tick() → [agent-level checks] → delegate to ToolPipeline → store_memory()

No Agent can unilaterally modify anything without:
  1. Constitution approval
  2. Sandbox isolation
  3. L3 review before flush

Execution chain delegated to ToolPipeline:
  clearance → rate_limit → constitution → alloc → pool → lock → execute → release
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from kernel import (
    get_event_bus, Signal, SignalType,
    get_limiter,
)
from kernel.constitution import get_constitution
from services.memory import get_memory as _get_mem

logger = logging.getLogger(__name__)


@dataclass
class Action:
    type: str         # tool_call | read_file | write_file | scout | think
    target: str       # file path or tool name or domain
    params: dict = field(default_factory=dict)
    acquired_locks: list[str] = field(default_factory=list)


class AgentRuntime:
    """Runtime for a single Agent process.

    1. tick() → memory refeed → resource check → delegate to ToolPipeline → store
    2. All writes go through sandbox, no direct project modification
    3. Constitution cannot be bypassed (enforced in ToolPipeline)
    """

    def __init__(self, agent_id: str, territory: list[str] | None = None):
        self.agent_id = agent_id
        self.territory = territory or []
        self.bus = get_event_bus()
        self.limiter = get_limiter()
        self.constitution = get_constitution()
        self.memory = _get_mem()
        self._active_tools = 0
        self._lock = threading.Lock()
        self._task_context: str = ""
        self._inference_id: int = 0

        self._handlers: dict[SignalType, Callable] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        self.on(SignalType.TASK_CANCEL, self._on_cancel)
        self.on(SignalType.CONSTITUTION_UPDATE, self._on_constitution_update)

    def on(self, signal_type: SignalType, handler: Callable) -> None:
        self._handlers[signal_type] = handler
        self.bus.on(signal_type, lambda sig: handler(sig) if sig.target in ("", self.agent_id) else None)

    def tick(self, action: Action | None = None) -> dict:
        """One execution cycle with enforcement chain.

        Agent-level phases (this method):
          1. Memory refeed (auto-load context before inference)
          2. Resource check (worker concurrency cap)

        Delegated to ToolPipeline:
          clearance → rate_limit → constitution → alloc → pool → lock → execute → release
        """
        if not action:
            return {"success": True, "idle": True}

        result = {"action": action.type, "target": action.target, "ticks": []}

        # ─── 1. Memory refeed (auto-load context before inference) ───
        if action.type in ("think", "tool_call"):
            self._inference_id += 1
            ctx = _get_mem().build_context(self.agent_id, max_tokens=2048)
            if ctx:
                self._task_context = ctx[:500]
                result["ticks"].append({"phase": "refeed", "tokens": len(ctx) // 4})

        # ─── 2. Resource check (workers) ───
        r = self.limiter.check(self.agent_id, "workers", cost=1)
        if not r["success"]:
            return {"success": False, "error": r["error"]}
        result["ticks"].append({"phase": "resource", **r})

        # ─── 3. Execute via ToolPipeline (handles constitution/gatechain/alloc/lock) ───
        with self._lock:
            self._active_tools += 1
        exec_result = {}
        try:
            from .services.tool_pipeline import ToolPipeline
            pipeline = ToolPipeline()
            exec_result = pipeline.execute(
                tool_name=action.target,
                agent_id=self.agent_id,
                args=action.params,
            )
            result["ticks"].append({"phase": "pipeline", "steps": exec_result.get("steps", [])})
            result["ticks"].append({
                "phase": "execute",
                "result": exec_result.get("result", exec_result),
                "success": exec_result.get("success", False),
            })
        except Exception as e:
            exec_result = {"success": False, "error": str(e)}
            result["ticks"].append({"phase": "execute", "result": exec_result, "success": False})
        with self._lock:
            self._active_tools -= 1

        if not exec_result.get("success", True):
            self.limiter.release(self.agent_id, "workers")
            return {"success": False, "error": exec_result.get("error", "execute failed"),
                    "ticks": result["ticks"]}

        # ─── 4. Memory store (auto-store after inference) ───
        if action.type in ("tool_call", "think", "decision"):
            _get_mem().remember(
                agent_id=self.agent_id,
                entry_type="tool_call" if action.type == "tool_call" else "observation",
                content=f"{action.type} {action.target}: {action.params.get('summary', '')}",
                tags=[action.type, action.target.split('/')[0] if '/' in action.target else action.target],
                ring=1,
            )
            result["ticks"].append({"phase": "memory_store", "ring": 1})

        # ─── 5. Release worker ───
        self.limiter.release(self.agent_id, "workers")

        return {"success": True, **result}

    def _on_cancel(self, sig: Signal) -> None:
        logger.warning("%s received CANCEL from %s", self.agent_id, sig.sender)
        self.limiter.release(self.agent_id, "workers")

    def _on_constitution_update(self, sig: Signal) -> None:
        logger.info("%s constitution updated: %s", self.agent_id, sig.data)

    def _release_all(self, action: Action | None = None) -> dict:
        """Stub kept for backward compatibility — locks now released by ToolPipeline."""
        return {"released": []}

    def status(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "territory": self.territory,
            "active_tools": self._active_tools,
            "held_locks": [],
            "resource_usage": self.limiter.usage(self.agent_id),
        }

    def emit(self, signal_type: SignalType, target: str = "", data: dict | None = None) -> None:
        sig = Signal(type=signal_type, sender=self.agent_id, target=target, data=data or {})
        self.bus.emit(sig)
