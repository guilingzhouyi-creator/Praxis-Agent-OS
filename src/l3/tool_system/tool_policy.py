"""ToolPolicy — multi-layer tool visibility policy.

Determines which tools an agent can see/use at three tiers:
  Tier 1 (handler binding):    ToolPolicy blocks → get_action_handler returns None
  Tier 2 (LLM context):        ToolPolicy blocks → no ToolDef sent to LLM
  Tier 3 (pipeline execution): ToolPolicy blocks → ToolPipeline rejects

Policy layers (priority: highest first):
  SESSION > AGENT > ROLE > CELL > GLOBAL

Integration with approval_gate:
  "require_approval" marks a tool as needing human approval.
  ApprovalGate handles the wait/approve/reject flow at execution time.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PolicyAction(str, Enum):
    """PolicyAction — enum of DISABLE, ENABLE, REQUIRE_APPROVAL."""
    DISABLE = "disable"
    ENABLE = "enable"
    REQUIRE_APPROVAL = "require_approval"


class PolicyScope(str, Enum):
    """PolicyScope — enum of GLOBAL, CELL, ROLE, AGENT...."""
    GLOBAL = "global"
    CELL = "cell"
    ROLE = "role"
    AGENT = "agent"
    SESSION = "session"

    @property
    def priority(self) -> int:
        return {
            "session": 5,
            "agent": 4,
            "role": 3,
            "cell": 2,
            "global": 1,
        }.get(self.value, 0)


@dataclass
class PolicyRule:
    """A single tool visibility rule."""
    scope: PolicyScope
    scope_id: str          # "agent-writer", "cell-1", "reader", ""
    tool: str              # tool name or "*" for all
    action: PolicyAction
    reason: str = ""

    def key(self) -> str:
        return f"{self.scope.value}:{self.scope_id}:{self.tool}"


class ToolPolicy:
    """Multi-layer tool visibility policy engine."""

    _lock = threading.Lock()
    _rules: list[PolicyRule] = []
    _agent_cache: dict[str, dict] = {}  # agent_id → {tool: (allowed, requires_approval)}

    # ── Agent identity helpers (injected from Cell at boot) ──

    _agent_role: dict[str, str] = {}     # agent_id → role
    _agent_cell: dict[str, str] = {}     # agent_id → cell_id

    @classmethod
    def register_agent(cls, agent_id: str, role: str, cell_id: str = "") -> None:
        cls._agent_role[agent_id] = role
        cls._agent_cell[agent_id] = cell_id

    @classmethod
    def _get_role(cls, agent_id: str) -> str:
        return cls._agent_role.get(agent_id, "")

    @classmethod
    def _get_cell(cls, agent_id: str) -> str:
        return cls._agent_cell.get(agent_id, "")

    # ── Rule management ──

    @classmethod
    def add(cls, rule: PolicyRule) -> None:
        with cls._lock:
            # Remove existing rule with same key
            cls._rules = [r for r in cls._rules if r.key() != rule.key()]
            cls._rules.append(rule)
            cls._agent_cache.clear()
            logger.info("tool_policy: %s %s for %s/%s",
                        rule.action.value, rule.tool, rule.scope.value, rule.scope_id)

    @classmethod
    def remove(cls, tool: str, scope: PolicyScope, scope_id: str = "") -> bool:
        key = f"{scope.value}:{scope_id}:{tool}"
        with cls._lock:
            before = len(cls._rules)
            cls._rules = [r for r in cls._rules if r.key() != key]
            cls._agent_cache.clear()
            return len(cls._rules) < before

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._rules.clear()
            cls._agent_cache.clear()

    @classmethod
    def list_rules(cls) -> list[dict]:
        with cls._lock:
            return [
                {"scope": r.scope.value, "scope_id": r.scope_id,
                 "tool": r.tool, "action": r.action.value, "reason": r.reason}
                for r in cls._rules
            ]

    # ── Policy evaluation ──

    @classmethod
    def is_allowed(cls, agent_id: str, tool_name: str) -> bool:
        _, allowed = cls._evaluate(agent_id, tool_name)
        return allowed

    @classmethod
    def requires_approval(cls, agent_id: str, tool_name: str) -> bool:
        needs_approval, _ = cls._evaluate(agent_id, tool_name)
        return needs_approval

    @classmethod
    def _evaluate(cls, agent_id: str, tool_name: str) -> tuple[bool, bool]:
        """Returns (requires_approval, allowed)."""
        # Check cache first (single lock acquisition)
        with cls._lock:
            cached = cls._agent_cache.get(agent_id, {}).get(tool_name)
            if cached is not None:
                return cached

        role = cls._get_role(agent_id)
        cell_id = cls._get_cell(agent_id)

        # Collect matching rules in priority order
        candidates = []
        with cls._lock:
            rules_snapshot = list(cls._rules)

        for r in rules_snapshot:
            if r.tool != "*" and r.tool != tool_name:
                continue
            if r.scope == PolicyScope.GLOBAL or r.scope == PolicyScope.CELL and r.scope_id == cell_id or r.scope == PolicyScope.ROLE and r.scope_id == role or r.scope == PolicyScope.AGENT and r.scope_id == agent_id or r.scope == PolicyScope.SESSION:
                candidates.append((r.scope.priority, r))

        # Sort by priority descending (highest wins)
        candidates.sort(key=lambda x: x[0], reverse=True)

        needs_approval = False
        allowed = True

        # candidates are sorted by priority DESCENDING, so the first
        # decisive action (DISABLE/ENABLE) wins; REQUIRE_APPROVAL is
        # additive and does not override a later decisive action.
        decided = False
        for _, r in candidates:
            if r.action == PolicyAction.DISABLE:
                allowed = False
                needs_approval = False
                decided = True
                break
            if r.action == PolicyAction.ENABLE:
                allowed = True
                needs_approval = False
                decided = True
                break
        if not decided:
            # Only REQUIRE_APPROVAL rules matched (or no decisive action).
            for _, r in candidates:
                if r.action == PolicyAction.REQUIRE_APPROVAL:
                    needs_approval = True
                    allowed = True
                    break

        # Cache result
        result = (needs_approval, allowed)
        with cls._lock:
            cls._agent_cache.setdefault(agent_id, {})[tool_name] = result

        return result

    # ── Persistence ──

    @classmethod
    def to_dict(cls) -> dict:
        rules = cls.list_rules()
        return {
            "blacklist": [r for r in rules if r["action"] == "disable"],
            "approval_required": [r for r in rules if r["action"] == "require_approval"],
            "overrides": [r for r in rules if r["action"] == "enable"],
        }

    @classmethod
    def load_from_yaml(cls, cfg: dict | None) -> None:
        """Load policy from praxis.yaml tool_policy: section."""
        if not cfg:
            return
        for entry in cfg.get("blacklist", []):
            scope, scope_id = cls._parse_scope(entry.get("scope", "global"))
            cls.add(PolicyRule(
                scope=scope, scope_id=scope_id,
                tool=entry["tool"], action=PolicyAction.DISABLE,
                reason=entry.get("reason", ""),
            ))
        for entry in cfg.get("approval_required", []):
            scope, scope_id = cls._parse_scope(entry.get("scope", "global"))
            cls.add(PolicyRule(
                scope=scope, scope_id=scope_id,
                tool=entry["tool"], action=PolicyAction.REQUIRE_APPROVAL,
                reason=entry.get("reason", ""),
            ))

    @staticmethod
    def _parse_scope(raw: str) -> tuple[PolicyScope, str]:
        """'agent:writer' → (PolicyScope.AGENT, 'writer'); 'global' → (GLOBAL, '')."""
        if ":" in raw:
            kind, sid = raw.split(":", 1)
            return PolicyScope(kind), sid
        return PolicyScope(raw), ""
