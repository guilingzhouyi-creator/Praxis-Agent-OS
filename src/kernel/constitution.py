"""Constitution engine — parses .nomos-rules.md into runtime constraints.

All Agent actions must pass constitution.check() before execution.
No Agent can unilaterally modify anything without constitutional approval.

Enforcement chain:
  Agent tick() → constitution.check() → resource.check() → lock → execute
                                    ↓
                             block if violates rules

Also provides:
  - load/parse/render/save for .nomos-rules.md files
  - merge_proposal for Assembly Mode territory convergence
  - diff for comparing constitutions
  - BLANK_CONSTITUTION template for new projects
"""

from __future__ import annotations

import logging
import os as _os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .params import (
    CONSTITUTION_ACTION_LEN_THRESHOLD,
    CONSTITUTION_CUSTOM_SECTION,
    CONSTITUTION_DEFAULT_PATH,
    CONSTITUTION_ENV_VAR,
    CONSTITUTION_FILE_ACTIONS,
    CONSTITUTION_FILE_EXT,
    CONSTITUTION_GATE_ACTIONS,
    CONSTITUTION_KEYWORD,
    CONSTITUTION_MODIFY_ACTIONS,
    CONSTITUTION_SCOUT_AGENT_NAME,
    CONSTITUTION_SCOUT_BLOCKED,
    CONSTITUTION_SHARED_KEYWORD,
    SANDBOX_ROOT_PATH,
)
from .rule_descriptor import RuleDescriptor, RuleSeverity, CheckResult, str_to_severity

logger = logging.getLogger(__name__)

# Configurable constitution path — env var override
_CONSTITUTION_FILE = _os.environ.get(CONSTITUTION_ENV_VAR, CONSTITUTION_DEFAULT_PATH)
CONSTITUTION_FILE = _CONSTITUTION_FILE

BLANK_CONSTITUTION = """# NOMOS Constitution
# Version: 1
# Territory definitions — empty, to be decided by Assembly Mode
# Format: agent_id: territory1, territory2, territory3

# GateChain rules
G1: workspace_fingerprint  # Tool whitelist
G2: identity_verification  # Identity verification
G3: permission_check       # Permission check
G4: compliance_scan        # Compliance scan
G5: report_decision        # Witness decision

# Defaults
default_reputation: 0.85
token_budget: 73000
"""


@dataclass
class CheckReport:
    """Result of evaluating a single rule against an action."""
    rule: RuleDescriptor
    result: CheckResult
    detail: str = ""


# ── Territory dataclass & helpers (for Assembly Mode) ──

@dataclass
class TerritoryConstitution:
    """Lightweight constitution data for territory management."""
    territories: dict[str, list[str]] = field(default_factory=dict)
    gate_rules: dict[str, str] = field(default_factory=dict)
    default_reputation: float = 0.85
    token_budget: int = 73000
    version: int = 1
    source: str = ""

    def is_blank(self) -> bool:
        return not self.territories


def _severity(s: str) -> RuleSeverity:
    return str_to_severity(s)


# ── Built-in check functions ──

def _check_territory(rule, action, agent_id, target, territory):
    if action not in CONSTITUTION_FILE_ACTIONS or not target:
        return CheckResult.PASS
    if territory and not any(target.startswith(t) for t in territory):
        return CheckResult.BLOCK if rule.severity == RuleSeverity.MUST else CheckResult.WARN
    return CheckResult.PASS


def _check_sandbox(rule, action, agent_id, target, territory):
    if action in CONSTITUTION_MODIFY_ACTIONS:
        if rule.severity == RuleSeverity.MUST and target:
            # Real path check: verify target starts with configured sandbox root
            abs_target = _os.path.abspath(target)
            return CheckResult.PASS if abs_target.startswith(SANDBOX_ROOT_PATH) else CheckResult.WARN
        return CheckResult.PASS
    return CheckResult.PASS


def _check_constitution_mod(rule, action, agent_id, target, territory):
    if not target:
        return CheckResult.PASS
    if CONSTITUTION_KEYWORD in target.lower():
        return CheckResult.BLOCK
    if target.endswith(CONSTITUTION_FILE_EXT):
        return CheckResult.BLOCK
    return CheckResult.PASS


def _check_gate(rule, action, agent_id, target, territory):
    if action in CONSTITUTION_GATE_ACTIONS:
        return CheckResult.WARN
    return CheckResult.WARN if action in CONSTITUTION_MODIFY_ACTIONS and len(action) > CONSTITUTION_ACTION_LEN_THRESHOLD else CheckResult.PASS


def _check_scout(rule, action, agent_id, target, territory):
    if agent_id == CONSTITUTION_SCOUT_AGENT_NAME:
        if action in CONSTITUTION_SCOUT_BLOCKED:
            return CheckResult.BLOCK
        if action in CONSTITUTION_FILE_ACTIONS:
            return CheckResult.PASS
    return CheckResult.PASS


def _check_audit(rule, action, agent_id, target, territory):
    return CheckResult.PASS


def _check_cross(rule, action, agent_id, target, territory):
    if action in CONSTITUTION_SCOUT_BLOCKED:
        if territory and any(CONSTITUTION_SHARED_KEYWORD in t.lower() for t in territory):
            return CheckResult.BLOCK
        return CheckResult.WARN
    return CheckResult.PASS


_BUILTIN_DESCRIPTORS: list[RuleDescriptor] = [
    RuleDescriptor(
        id="territory.write", section="§2.3",
        severity=RuleSeverity.MUST,
        description="Agent must not write outside its territory",
        check_fn=_check_territory,
        tags=frozenset({"territory", "write"}),
    ),
    RuleDescriptor(
        id="territory.read_l3", section="§3.1",
        severity=RuleSeverity.MUST,
        description="Agent must not read files outside its territory without L3 approval",
        check_fn=_check_territory,
        tags=frozenset({"territory", "read"}),
    ),
    RuleDescriptor(
        id="gatechain.all", section="§3.3",
        severity=RuleSeverity.MUST,
        description="All tool calls must pass GateChain G1-G5",
        check_fn=_check_gate,
        tags=frozenset({"gatechain"}),
    ),
    RuleDescriptor(
        id="gatechain.cross", section="§3.4",
        severity=RuleSeverity.MUST,
        description="Cross-unit tool calls require G5 approval",
        check_fn=_check_gate,
        tags=frozenset({"gatechain", "cross"}),
    ),
    RuleDescriptor(
        id="sandbox.writes", section="§4.5",
        severity=RuleSeverity.MUST,
        description="All modifications must go through sandbox (no direct writes)",
        check_fn=_check_sandbox,
        tags=frozenset({"sandbox"}),
    ),
    RuleDescriptor(
        id="sandbox.review", section="§4.6",
        severity=RuleSeverity.MUST,
        description="All modifications must be reviewable by L3 before flush",
        check_fn=_check_sandbox,
        tags=frozenset({"sandbox", "review"}),
    ),
    RuleDescriptor(
        id="constitution.modify", section="§4.7",
        severity=RuleSeverity.MUST,
        description="No Agent may modify the constitution itself",
        check_fn=_check_constitution_mod,
        tags=frozenset({"constitution"}),
    ),
    RuleDescriptor(
        id="audit.trail", section="§5.1",
        severity=RuleSeverity.MUST,
        description="All tool calls must be logged with audit trail",
        check_fn=_check_audit,
        tags=frozenset({"audit"}),
    ),
    RuleDescriptor(
        id="decision.memory", section="§5.2",
        severity=RuleSeverity.SHOULD,
        description="All decisions must be recorded in memory Ring 2",
        check_fn=None,
        tags=frozenset({"memory"}),
    ),
    RuleDescriptor(
        id="territory.cross_review", section="§6.1",
        severity=RuleSeverity.MUST,
        description="Cross-territory changes require peer review",
        check_fn=_check_cross,
        tags=frozenset({"territory", "review"}),
    ),
    RuleDescriptor(
        id="l3.arbiter", section="§6.2",
        severity=RuleSeverity.MUST,
        description="L3 is the final arbiter of all disputes",
        check_fn=None,
        tags=frozenset({"l3"}),
    ),
    RuleDescriptor(
        id="scout.readonly", section="§7.1",
        severity=RuleSeverity.MUST,
        description="Scouts are read-only and depth=1",
        check_fn=_check_scout,
        tags=frozenset({"scout"}),
    ),
    RuleDescriptor(
        id="scout.log", section="§7.2",
        severity=RuleSeverity.SHOULD,
        description="Scout findings must be logged before disposal",
        check_fn=_check_scout,
        tags=frozenset({"scout", "audit"}),
    ),
    RuleDescriptor(
        id="ring.context", section="§8.1",
        severity=RuleSeverity.MUST,
        description="Agent context must be built from Ring memory, not raw output",
        check_fn=None,
        tags=frozenset({"memory", "ring"}),
    ),
    RuleDescriptor(
        id="ring.persist", section="§8.2",
        severity=RuleSeverity.SHOULD,
        description="Important decisions must be persisted to Ring 3 (long-term)",
        check_fn=None,
        tags=frozenset({"memory", "ring"}),
    ),
]


# ═════════════════════════════════════════════════════════════════════════════
# TerritoryConstitution functions (for Assembly Mode / territory management)
# ═════════════════════════════════════════════════════════════════════════════

def load_territory(path: str = "") -> TerritoryConstitution:
    """Load territory constitution from file. Returns blank if not found."""
    if not path:
        path = _CONSTITUTION_FILE
    p = Path(path)
    if not p.exists():
        return TerritoryConstitution(source="blank")
    return parse_territory(p.read_text(encoding="utf-8"), source=str(p))


def parse_territory(text: str, source: str = "") -> TerritoryConstitution:
    """Parse territory constitution text into a TerritoryConstitution."""
    c = TerritoryConstitution(source=source)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip(); value = value.strip()
        if key.startswith("agent_"):
            c.territories[key] = [t.strip() for t in value.split(",") if t.strip()]
        elif key.startswith("G") and len(key) <= 3:
            c.gate_rules[key] = value
        elif key == "default_reputation":
            try: c.default_reputation = float(value)
            except Exception:
                logger.warning("constitution: invalid default_reputation: %s", value)
        elif key == "token_budget":
            try: c.token_budget = int(value)
            except Exception:
                logger.warning("constitution: invalid token_budget: %s", value)
        elif key == "version":
            try: c.version = int(value)
            except Exception:
                logger.warning("constitution: invalid version: %s", value)
    return c


def render_territory(c: TerritoryConstitution) -> str:
    """Render a TerritoryConstitution back to markdown text."""
    lines = ["# NOMOS Constitution", f"# Version: {c.version}", ""]
    lines.append("# Territory definitions")
    for agent_id, territories in c.territories.items():
        lines.append(f"{agent_id}: {', '.join(territories)}")
    lines.append("")
    lines.append("# GateChain rules")
    for gate, desc in c.gate_rules.items():
        lines.append(f"{gate}: {desc}")
    lines.append("")
    lines.append("# Defaults")
    lines.append(f"default_reputation: {c.default_reputation}")
    lines.append(f"token_budget: {c.token_budget}")
    return "\n".join(lines) + "\n"


def save_territory(c: TerritoryConstitution, path: str = "") -> dict:
    """Save territory constitution to file."""
    if not path:
        path = _CONSTITUTION_FILE
    try:
        Path(path).write_text(render_territory(c), encoding="utf-8")
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_territory(c: TerritoryConstitution, agent_id: str, new_territories: list[str]) -> dict:
    """Update a single agent's territory."""
    c.territories[agent_id] = new_territories
    c.version += 1
    return {"success": True, "agent_id": agent_id, "territories": new_territories, "version": c.version}


def merge_proposal(c: TerritoryConstitution, proposal: dict) -> dict:
    """Merge a proposal from Assembly Mode into the constitution."""
    for agent_id, territories in proposal.items():
        if agent_id.startswith("agent_"):
            c.territories[agent_id] = territories
    c.version += 1
    save_territory(c)
    return {"success": True, "agents": list(proposal.keys()), "version": c.version}


def diff_territory(old: TerritoryConstitution, new: TerritoryConstitution) -> dict:
    """Compare two territory constitutions and return differences."""
    changes = {}
    for agent_id in set(list(old.territories.keys()) + list(new.territories.keys())):
        old_t = set(old.territories.get(agent_id, []))
        new_t = set(new.territories.get(agent_id, []))
        added = new_t - old_t; removed = old_t - new_t
        if added or removed:
            changes[agent_id] = {"added": list(added), "removed": list(removed)}
    return {"changed": len(changes) > 0, "changes": changes}


# ═════════════════════════════════════════════════════════════════════════════
# Constitution engine (rule checking)
# ═════════════════════════════════════════════════════════════════════════════

class Constitution:
    """Constitution engine — the highest authority in the Agent OS.

    All rules are immutable at runtime (can only be changed by modifying
    the constitution file and restarting the system).
    """

    def __init__(self):
        self._rules: list[RuleDescriptor] = list(_BUILTIN_DESCRIPTORS)
        self._lock = threading.Lock()
        self._constitution_path: str = ""

    def load(self, path: str = "") -> dict:
        """Load constitution from .nomos-rules.md file."""
        if not path:
            path = _CONSTITUTION_FILE
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return {"success": False, "error": f"constitution not found: {path}"}

        custom_rules = self._parse_markdown(content)
        with self._lock:
            self._constitution_path = path
            self._rules = list(_BUILTIN_DESCRIPTORS) + custom_rules
        return {"success": True, "rules": len(self._rules), "custom": len(custom_rules), "path": path}

    def check(self, action: str, agent_id: str, target: str = "",
              territory: list[str] | None = None) -> list[CheckReport]:
        reports: list[CheckReport] = []
        for rule in self._rules:
            result = self._evaluate(rule, action, agent_id, target, territory or [])
            if result != CheckResult.PASS:
                reports.append(CheckReport(rule=rule, result=result,
                                           detail=self._describe(rule, action, agent_id, target)))
        return reports

    def is_allowed(self, action: str, agent_id: str, target: str = "",
                   territory: list[str] | None = None) -> dict:
        reports = self.check(action, agent_id, target, territory)
        blocks = [r for r in reports if r.result == CheckResult.BLOCK]
        return {
            "allowed": len(blocks) == 0,
            "decision": "pass" if not blocks else "block",
            "blocks": len(blocks),
            "warns": len([r for r in reports if r.result == CheckResult.WARN]),
            "details": [{"section": r.rule.section, "result": r.result.name, "detail": r.detail}
                        for r in reports],
        }

    def rules_list(self) -> list[dict]:
        with self._lock:
            return [{"section": r.section, "severity": r.severity.name, "description": r.description}
                    for r in self._rules]

    def _evaluate(self, rule, action, agent_id, target, territory) -> CheckResult:
        return rule.evaluate(action, agent_id, target, territory)

    def _describe(self, rule, action, agent_id, target) -> str:
        return f"{rule.section}: {rule.description} (action={action}, agent={agent_id}, target={target})"

    @staticmethod
    def _parse_markdown(content: str) -> list[RuleDescriptor]:
        rules: list[RuleDescriptor] = []
        current_section = ""
        for line in content.splitlines():
            m = re.match(r"^##+\s+(.+)$", line)
            if m:
                current_section = m.group(1).strip()
            sev = None
            if "[MUST]" in line: sev = RuleSeverity.MUST
            elif "[SHOULD]" in line: sev = RuleSeverity.SHOULD
            elif "[MAY]" in line: sev = RuleSeverity.MAY
            if sev:
                desc = re.sub(r"\[(MUST|SHOULD|MAY)\]", "", line).strip()
                if desc:
                    rules.append(RuleDescriptor(
                        id=f"custom.{len(rules)}",
                        section=current_section or CONSTITUTION_CUSTOM_SECTION,
                        severity=sev, description=desc,
                        source="custom",
                    ))
        return rules


_constitution: Constitution | None = None


def get_constitution() -> Constitution:
    global _constitution
    if _constitution is None:
        _constitution = Constitution()
    return _constitution


def reset_constitution() -> None:
    global _constitution
    _constitution = None
