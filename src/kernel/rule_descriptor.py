"""Rule descriptor — unified rule definition + evaluation for Constitution.

Each built-in or custom rule is represented as a single RuleDescriptor
instance that bundles:
  - Rule identity (id, section, severity, description, tags)
  - Evaluation logic (check_fn)
  - Source tracking (builtin / custom)

Eliminates the string-keyed mapping between BUILTIN_RULE_DEFS (params.py)
and _BUILTIN_CHECKERS (constitution.py) — no more fragile description
string lookups.

Usage:
    from kernel.rule_descriptor import RuleDescriptor

    rule = RuleDescriptor(
        id="territory.write",
        section="§2.3",
        severity=RuleSeverity.MUST,
        description="Agent must not write outside its territory",
        check_fn=_check_territory,
        tags={"territory", "write"},
    )
    result = rule.evaluate(action, agent_id, target, territory)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class RuleSeverity(Enum):
    MUST = auto()
    SHOULD = auto()
    MAY = auto()


class CheckResult(Enum):
    PASS = auto()
    WARN = auto()
    BLOCK = auto()


def str_to_severity(s: str) -> RuleSeverity:
    """Convert string 'MUST'|'SHOULD'|'MAY' to RuleSeverity enum."""
    return {"MUST": RuleSeverity.MUST,
            "SHOULD": RuleSeverity.SHOULD,
            "MAY": RuleSeverity.MAY}.get(s, RuleSeverity.MAY)


# Type alias for check functions: (rule, action, agent_id, target, territory) → CheckResult | None
CheckFn = Callable[..., CheckResult | None]


@dataclass(frozen=True)
class RuleDescriptor:
    """Single immutable rule — id, definition, and evaluation.

    Each descriptor carries its own *check_fn* so the mapping between
    rule text and check logic is explicit and cannot drift.

    Fields:
        id:         Unique machine-readable identifier (e.g. ``"territory.write"``).
        section:    Constitution section (e.g. ``"§2.3"``).
        severity:   MUST / SHOULD / MAY.
        description: Human-readable rule text.
        check_fn:   Callable invoked during ``evaluate()``; *None* means always PASS.
        source:     ``"builtin"`` or ``"custom"``.
        tags:       Classification tags (e.g. ``{"territory", "sandbox"}``).
        created_at: Timestamp of creation.
    """

    id: str
    section: str
    severity: RuleSeverity
    description: str
    check_fn: CheckFn | None = None
    source: str = "builtin"
    tags: frozenset[str] = field(default_factory=frozenset)
    created_at: float = field(default_factory=time.time)

    def evaluate(self, action: str, agent_id: str, target: str = "",
                 territory: list[str] | None = None) -> CheckResult:
        """Evaluate this rule against an action. Returns CheckResult.

        If ``check_fn`` is *None* the rule always passes.
        ``check_fn`` receives ``(self, action, agent_id, target, territory)``.
        """
        if self.check_fn is not None:
            result = self.check_fn(self, action, agent_id, target, territory or [])
            if result is not None:
                return result
        return CheckResult.PASS

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "section": self.section,
            "severity": self.severity.name,
            "description": self.description,
            "source": self.source,
            "tags": sorted(self.tags),
        }
