"""ToolMiddleware — composable tool-level hooks, separated from tool_pipeline.

Each middleware implements before/after hooks for a single concern:
  - ApprovalMiddleware: human approval gate (using ApprovalGate + PendingQueue)
  - ConfineMiddleware: path confinement for read-only tool sets
  - ArgRepairMiddleware: lenient argument deserialization
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BeforeOutcome:
    PROCEED = "proceed"
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class AfterOutcome:
    PROCEED = "proceed"
    BLOCK = "block"


class ToolMiddleware:
    """Base class for tool-level middleware."""

    def before(self, tool_name: str, args: dict,
               agent_id: str, ctx: dict | None = None) -> str:
        """Called before tool execution. Returns a BeforeOutcome."""
        return BeforeOutcome.PROCEED

    def after(self, tool_name: str, result: dict,
              agent_id: str) -> str:
        """Called after tool execution. Returns an AfterOutcome."""
        return AfterOutcome.PROCEED


class MiddlewareChain:
    """Compose multiple tool middlewares into one."""

    def __init__(self):
        self._middlewares: list[ToolMiddleware] = []

    def add(self, mw: ToolMiddleware) -> None:
        self._middlewares.append(mw)

    def before(self, tool_name: str, args: dict,
               agent_id: str, ctx: dict | None = None) -> str:
        for mw in self._middlewares:
            outcome = mw.before(tool_name, args, agent_id, ctx)
            if outcome in (BeforeOutcome.DENY, BeforeOutcome.ASK):
                return outcome
            if outcome == BeforeOutcome.ALLOW:
                continue
        return BeforeOutcome.PROCEED

    def after(self, tool_name: str, result: dict, agent_id: str) -> str:
        for mw in self._middlewares:
            outcome = mw.after(tool_name, result, agent_id)
            if outcome == AfterOutcome.BLOCK:
                return outcome
        return AfterOutcome.PROCEED


# ── Built-in middleware implementations ──


class ApprovalMiddleware(ToolMiddleware):
    """Human approval gate — blocks dangerous tools pending approval.

    Uses ApprovalGate + PendingQueue as the backend.
    """

    def __init__(self):
        self._auto_approved: set[str] = set()

    def before(self, tool_name: str, args: dict,
               agent_id: str, ctx: dict | None = None) -> str:
        try:
            from l3.tool_policy import ToolPolicy
            if not ToolPolicy.requires_approval(agent_id, tool_name):
                return BeforeOutcome.PROCEED
        except Exception:
            pass

        # Check if auto-approved in this session
        key = f"{agent_id}:{tool_name}"
        if key in self._auto_approved:
            return BeforeOutcome.PROCEED

        # Auto-approve if not dangerous
        try:
            from l3.settings_center import get_center
            threshold = get_center().get_int("approval.danger_threshold", 3)
        except Exception:
            threshold = 3

        try:
            from l3.tool_spec import get_tool
            spec = get_tool(tool_name)
            if spec and getattr(spec, "danger", 0) < threshold:
                return BeforeOutcome.PROCEED
        except Exception:
            pass

        # Request approval
        try:
            from l3.approval_gate import get_gate
            gate = get_gate()
            gate.request(
                tool_name=tool_name,
                agent_id=agent_id,
                args=args,
                reason=f"danger >= {threshold}",
            )
            return BeforeOutcome.ASK
        except Exception as e:
            logger.warning("ApprovalMiddleware: %s", e)
            return BeforeOutcome.PROCEED

    def auto_approve(self, agent_id: str, tool_name: str) -> None:
        """Mark a tool as auto-approved for this session."""
        self._auto_approved.add(f"{agent_id}:{tool_name}")


class ConfineMiddleware(ToolMiddleware):
    """Path confinement — restricts tool arguments to allowed paths.

    Used by review/deploy sub-agents to prevent writes outside their scope.
    """

    def __init__(self, allowed_roots: list[str] | None = None,
                 read_only: bool = False):
        self._allowed_roots = allowed_roots or []
        self._read_only = read_only

    def before(self, tool_name: str, args: dict,
               agent_id: str, ctx: dict | None = None) -> str:
        if not self._allowed_roots:
            return BeforeOutcome.PROCEED

        path = args.get("path", args.get("target", ""))
        if not path:
            return BeforeOutcome.PROCEED

        allowed = any(path.startswith(root) for root in self._allowed_roots)
        if not allowed:
            logger.warning("ConfineMiddleware: blocked %s path=%s", tool_name, path)
            return BeforeOutcome.DENY

        return BeforeOutcome.PROCEED


class ArgRepairMiddleware(ToolMiddleware):
    """Lenient argument deserialization — handles common edge cases.

    - Trims whitespace from values
    - Converts string 'true'/'false' to bool
    - Strips leading/trailing quotes
    """

    def before(self, tool_name: str, args: dict,
               agent_id: str, ctx: dict | None = None) -> str:
        for k, v in list(args.items()):
            if isinstance(v, str):
                v = v.strip().strip("\"'")
                if v.lower() in ("true", "yes"):
                    args[k] = True
                elif v.lower() in ("false", "no"):
                    args[k] = False
                else:
                    args[k] = v
        return BeforeOutcome.PROCEED
