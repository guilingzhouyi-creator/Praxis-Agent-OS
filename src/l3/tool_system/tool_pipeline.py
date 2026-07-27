"""Tool pipeline — ring-gated tool execution for Cells.

Integrates with TOOL_REGISTRY at runtime via tools.execute_tool.
No direct import of tool_spec (avoids relative import issues).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from l1.kernel import Signal, SignalType, get_event_bus, get_rwlock, get_semaphore
from l1.kernel.allocator import get_allocator
from l1.kernel.constitution import get_constitution
from l1.kernel.params.agent import SCOUT_AGENT_NAME, SCOUT_RING_LIMIT
from l1.kernel.params.kernel import RING_1 as _RING_1, RING_2_5, RING_NUM_MAP
from l1.kernel.params.tool import TOOL_EXEC_TOKEN_BUDGET
from l1.kernel.params.system import APPROVAL_GATE_WAIT_TIMEOUT
from l1.kernel.tool_chain import get_tool_chain

from .scheduler.scheduler_rate import agent_can_access, get_rate_scheduler

logger = logging.getLogger(__name__)


class ToolPipeline:
    """Gated execution: clearance → constitution → alloc → lock → execute.

    Supports external hooks:
      - Post-execute hooks: called after tool execution with result
      - Tool-definition hooks: modify tool spec before execution
    """

    def __init__(self):
        self.constitution = get_constitution()
        self.allocator = get_allocator()
        self.bus = get_event_bus()
        self._rate_scheduler = get_rate_scheduler()
        self._post_execute_hooks: list[Callable] = []
        self._tool_definition_hooks: list[Callable] = []
        self._pmu: Any = None

    def set_pmu(self, pmu: Any) -> None:
        """Attach a Cell PMU for tool execution counters."""
        self._pmu = pmu

    def register_post_execute_hook(self, hook: Callable) -> None:
        """Register a hook called after every tool execution.

        Hook signature: (tool_name: str, agent_id: str, args: dict, result: dict) -> dict
        The hook can modify the result dict.
        """
        if hook not in self._post_execute_hooks:
            self._post_execute_hooks.append(hook)

    def register_tool_definition_hook(self, hook: Callable) -> None:
        """Register a hook that modifies tool specs before execution.

        Hook signature: (tool_name: str, spec: ToolSpec | None) -> dict | None
        Returns modified spec fields or None to leave unchanged.
        """
        if hook not in self._tool_definition_hooks:
            self._tool_definition_hooks.append(hook)

    def _run_post_execute_hooks(self, tool_name: str, agent_id: str,
                                args: dict, result: dict) -> dict:
        """Run all registered post-execute hooks in order."""
        current = dict(result)
        for hook in self._post_execute_hooks:
            try:
                r = hook(tool_name, agent_id, args, current)
                if isinstance(r, dict):
                    current.update(r)
            except Exception as e:
                logger.warning("post-execute hook failed for %s: %s", tool_name, e)
        return current

    def apply_tool_definition_hooks(self, tool_name: str, spec: Any) -> Any:
        """Let hooks modify tool spec before execution."""
        if not self._tool_definition_hooks:
            return spec
        for hook in self._tool_definition_hooks:
            try:
                r = hook(tool_name, spec)
                if isinstance(r, dict) and spec is not None:
                    from .tool_system.tool_spec import ToolSpec as _ToolSpec
                    if isinstance(spec, _ToolSpec):
                        for k, v in r.items():
                            if hasattr(spec, k):
                                setattr(spec, k, v)
            except Exception as e:
                logger.warning("tool-definition hook failed for %s: %s", tool_name, e)
        return spec

    def execute(self, tool_name: str, agent_id: str,
                args: dict | None = None,
                _registry: dict | None = None,
                _executor: Any = None,
                _parent_call_id: str = "") -> dict:
        """Execute a tool through the pipeline with hierarchical call tracking.

        Args:
            _registry: TOOL_REGISTRY dict (passed by caller)
            _executor: execute_tool function (passed by caller)
            _parent_call_id: parent composite tool's call_id for chain tracking
        """
        import time as _time

        from .tool_system.tool_spec import ToolSpec as _ToolSpec
        _start = _time.time()
        chain = get_tool_chain()
        ring_map = RING_NUM_MAP  # single source: kernel.params.RING_NUM_MAP
        spec_raw = (_registry or {}).get(tool_name) if _registry else None
        spec = spec_raw if isinstance(spec_raw, _ToolSpec) else None
        tool_ring_str = spec.ring if spec else _RING_1
        tool_ring_num = ring_map.get(tool_ring_str, 1)

        tool_danger = spec.danger if spec else 0
        call_id = chain.start(tool_name, agent_id, ring=tool_ring_num,
                               parent_id=_parent_call_id)
        result: dict[str, Any] = {"tool": tool_name, "agent": agent_id,
                                   "ring": tool_ring_str, "danger": tool_danger,
                                   "steps": [], "call_id": call_id}

        # 1. Validate tool exists
        if not _registry and not _executor:
            return {"success": False, "error": "pipeline not initialized with registry"}

        # 2. Clearance
        if not agent_can_access(agent_id, tool_ring_str):
            return {"success": False, "error": f"no clearance for {tool_ring_str}"}

        # 3. Scout restriction (single source: kernel.params.SCOUT_*)
        if agent_id == SCOUT_AGENT_NAME and tool_ring_str != SCOUT_RING_LIMIT:
            return {"success": False, "error": "scout: Ring 1 only"}

        # 3b. ToolPolicy approval check
        try:
            from .tool_system.tool_policy import ToolPolicy as _TP
            if _TP.requires_approval(agent_id, tool_name):
                from .card.approval_gate import get_gate as _gg
                ar = _gg().request(tool_name, agent_id, args or {}, reason="policy requires approval")
                result["steps"].append({"phase": "approval", "request_id": ar.id, "status": "pending"})
                status = ar.wait(timeout=APPROVAL_GATE_WAIT_TIMEOUT)
                if status != "approved":
                    return {"success": False, "error": f"approval {status}", "approval_id": ar.id,
                            "steps": result["steps"]}
                result["steps"].append({"phase": "approval", "request_id": ar.id, "status": status})
        except Exception as e:
            logger.warning("approval check failed: %s", e)

        # 4. Rate limit (Ring 3 slowest, Ring 1 fastest)
        rr = self._rate_scheduler.check(agent_id, tool_ring_str)
        result["steps"].append({"phase": "rate", **rr})
        if not rr["allowed"]:
            self.allocator.free(agent_id, "tokens", TOOL_EXEC_TOKEN_BUDGET)
            return {"success": False, "error": f"rate limited ({tool_ring_str})",
                    "rate": rr, "steps": result["steps"]}

        # 5. Constitution (pass file path as target for territory enforcement)
        fpath = (args or {}).get("path", "")
        territory_str = (args or {}).get("territory", "")
        cc = self.constitution.is_allowed(tool_name, agent_id,
                                          target=fpath or tool_name,
                                          territory=territory_str)
        result["steps"].append({"phase": "constitution", **cc})
        if not cc["allowed"]:
            return {"success": False, "error": "constitution blocked", "steps": result["steps"]}

        # 5b. GateChain G1-G5
        try:
            from l1.kernel.gatechain import get_gatechain as _gc
            gcr = _gc().check(tool_name, agent_id, target=fpath,
                              territory=[territory_str] if territory_str else None)
            gc_allowed = gcr.get("allowed", True)
            result["steps"].append({"phase": "gatechain", "decision": gcr.get("decision", "?"),
                                    "steps": gcr.get("steps", [])})
            if not gc_allowed:
                return {"success": False, "error": "gatechain blocked",
                        "gate_result": gcr, "steps": result["steps"]}
        except Exception as e:
            logger.error("gatechain check failed, blocking: %s", e)
            result["steps"].append({"phase": "gatechain", "decision": "BLOCK", "error": str(e)})
            return {"success": False, "error": f"gatechain unavailable: {e}", "steps": result["steps"]}

        # 5c. Sandbox gate (for terminal/process tools with sandbox_profile)
        try:
            _sb_profile = spec.sandbox_profile if spec else None
            if _sb_profile:
                from l4.sandbox.manager import SandboxManager, SandboxProfile
                _sb = SandboxManager()
                _sb_cmd = (args or {}).get("command", "")
                _sb_to = (args or {}).get("timeout", 30)
                _sb_r = _sb.run_sync(_sb_cmd, SandboxProfile(_sb_profile), _sb_to, agent_id, tool_name)
                result["steps"].append({"phase": "sandbox", "sandbox_id": _sb_r.sandbox_id,
                                        "success": _sb_r.success, "elapsed": _sb_r.elapsed})
                if not _sb_r.success:
                    return {"success": False, "error": f"sandbox: {_sb_r.stderr[:200]}",
                            "sandbox": _sb_r.to_dict(), "steps": result["steps"]}
                # Sandbox succeeded: record result and skip execute step
                result["result"] = _sb_r.to_dict()
                result["success"] = True
                for _hook in self._post_execute_hooks:
                    try:
                        _hook(tool_name, agent_id, args or {}, result)
                    except Exception:
                        pass
                # Release and signal
                if lock_name:
                    get_rwlock(lock_name).unlock(agent_id)
                if tool_ring_str == RING_2_5:
                    get_semaphore(f"pool:{tool_name}").release(agent_id)
                self.allocator.free(agent_id, "tokens", TOOL_EXEC_TOKEN_BUDGET)
                duration = _time.time() - _start
                chain.complete(call_id, success=True, duration=duration)
                result["call_id"] = call_id
                return result
        except Exception as e:
            logger.warning("sandbox gate failed: %s", e)

        # 6. Alloc
        ar = self.allocator.alloc(agent_id, "tokens", TOOL_EXEC_TOKEN_BUDGET, tool_name)
        result["steps"].append({"phase": "alloc", **ar})
        if not ar["success"]:
            return {"success": False, "error": ar["error"], "steps": result["steps"]}

        # 7. Ring 2.5 pool
        if tool_ring_str == RING_2_5:
            sr = get_semaphore(f"pool:{tool_name}", 2).acquire(agent_id)
            result["steps"].append({"phase": "pool", **sr})
            if not sr["success"]:
                self.allocator.free(agent_id, "tokens", TOOL_EXEC_TOKEN_BUDGET)
                return {"success": False, "error": "pool busy", "steps": result["steps"]}

        # 8. File lock
        lock_name = ""
        if fpath:
            lock_name = f"file:{fpath}"
            lr = get_rwlock(lock_name).write_lock(agent_id) if tool_ring_str != RING_1 else get_rwlock(lock_name).read_lock(agent_id)
            result["steps"].append({"phase": "lock", **lr})

        # 8b. Tool-definition hooks (modify spec before execution)
        spec = self.apply_tool_definition_hooks(tool_name, spec)

        # 9. Execute (default: execute_tool_spec for middleware/result store/counter)
        from l3.error_bus import error_boundary
        with error_boundary("tool execute failed", component="services", agent_id=agent_id):
            if _executor:
                exec_r = _executor(tool_name, args or {}, agent_id=agent_id)
            else:
                from .tool_system.tool_spec import execute_tool_spec as _ets
                exec_r = _ets(tool_name, args or {}, agent_id=agent_id)
            result["result"] = exec_r or {}
            result["success"] = (exec_r or {}).get("success", True)
            # PMU: count tool execution by ring
            if self._pmu:
                ring_label = tool_ring_str.replace(".", "_")
                self._pmu.increment(f"tools.executed.{ring_label}")
                if not result["success"]:
                    self._pmu.increment("tools.rejected")

        # 10. Release
        if lock_name:
            get_rwlock(lock_name).unlock(agent_id)
        if tool_ring_str == RING_2_5:
            get_semaphore(f"pool:{tool_name}").release(agent_id)
        self.allocator.free(agent_id, "tokens", TOOL_EXEC_TOKEN_BUDGET)

        # 10b. Post-execute hooks (transform result)
        result = self._run_post_execute_hooks(tool_name, agent_id, args or {}, result)

        # 10. Complete chain call
        duration = _time.time() - _start
        link = chain.get(call_id)
        chain.complete(call_id, success=result.get("success", False),
                       error=result.get("error", ""), duration=duration)
        result["call_id"] = call_id
        result["parent_call_id"] = _parent_call_id
        result["fingerprint"] = link.fingerprint if link else ""

        # Chain data stays in tool_chain module only — NOT pushed to LLM context.
        # This preserves LLM inference caching.  Chain is queryable on demand
        # via kernel.tool_chain.get_tool_chain().verify(call_id).

        # 11. Signal
        agent_key = agent_id.replace("agent_", "") if agent_id.startswith("agent_") else agent_id
        sig_type = SignalType.SCOUT_DONE if agent_key == SCOUT_AGENT_NAME else SignalType.TASK_ASSIGN
        self.bus.emit(Signal(type=sig_type, sender=agent_id, target="cell",
                              data={"tool": tool_name, "call_id": call_id,
                                    "success": result["success"]}))
        return result


_pipeline: ToolPipeline | None = None


def get_pipeline() -> ToolPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ToolPipeline()
    return _pipeline


def reset_pipeline() -> None:
    global _pipeline
    _pipeline = None
