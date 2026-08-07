"""Constitution engine — parses .praxis-rules.md into runtime constraints.

All Agent actions must pass constitution.check() before execution.
No Agent can unilaterally modify anything without constitutional approval.

Enforcement chain:
  Agent tick() → constitution.check() → resource.check() → lock → execute
                                    ↓
                             block if violates rules

Also provides:
  - load/parse/render/save for .praxis-rules.md files
  - merge_proposal for Assembly Mode territory convergence
  - diff for comparing constitutions
  - BLANK_CONSTITUTION template for new projects
"""

from __future__ import annotations

import logging
import os as _os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from l1.kernel.discovery import get_config

from .params.agent import (
    CONSTITUTION_ACTION_LEN_THRESHOLD,
    CONSTITUTION_CUSTOM_SECTION,
    CONSTITUTION_DEFAULT_PATH,
    CONSTITUTION_ENV_VAR,
    CONSTITUTION_FILE_EXT,
    CONSTITUTION_GATE_ACTIONS,
    CONSTITUTION_KEYWORD,
    CONSTITUTION_SCOUT_AGENT_NAME,
    CONSTITUTION_SCOUT_BLOCKED,
    CONSTITUTION_SHARED_KEYWORD,
    REP_DEFAULT_REPUTATION,
    SANDBOX_ROOT_PATH,
)
from .params.system import DEFAULT_TOKEN_BUDGET, SKILL_POSTURE_OFFENSIVE
from .rule_descriptor import CheckResult, RuleDescriptor, RuleSeverity, str_to_severity

logger = logging.getLogger(__name__)

# Configurable constitution path — env var override
_CONSTITUTION_FILE = _os.environ.get(CONSTITUTION_ENV_VAR, CONSTITUTION_DEFAULT_PATH)

# ── Tag constants for built-in descriptors ──
TAG_TERRITORY_WRITE = frozenset({"territory", "write"})
TAG_TERRITORY_READ = frozenset({"territory", "read"})
TAG_GATECHAIN = frozenset({"gatechain"})
TAG_GATECHAIN_CROSS = frozenset({"gatechain", "cross"})
TAG_SANDBOX = frozenset({"sandbox"})
TAG_SANDBOX_REVIEW = frozenset({"sandbox", "review"})
TAG_CONSTITUTION = frozenset({"constitution"})
TAG_AUDIT = frozenset({"audit"})
TAG_MEMORY = frozenset({"memory"})
TAG_TERRITORY_REVIEW = frozenset({"territory", "review"})
TAG_L3 = frozenset({"l3"})
TAG_SCOUT = frozenset({"scout"})
TAG_SCOUT_AUDIT = frozenset({"scout", "audit"})
TAG_MEMORY_RING = frozenset({"memory", "ring"})
TAG_SKILL = frozenset({"skill"})

CONSTITUTION_SOURCE_BLANK = "blank"

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
    default_reputation: float = REP_DEFAULT_REPUTATION
    token_budget: int = DEFAULT_TOKEN_BUDGET
    version: int = 1
    source: str = ""

    def is_blank(self) -> bool:
        """Return True if no territories are defined."""
        return not self.territories


def _severity(s: str) -> RuleSeverity:
    return str_to_severity(s)


# ── Built-in check functions ──

def _check_territory(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    ca = get_config("constitution")
    if ca:
        file_actions = frozenset(ca.get("file_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_FILE_ACTIONS
        file_actions = CONSTITUTION_FILE_ACTIONS
    if action not in file_actions or not target:
        return CheckResult.PASS
    if territory and not any(target.startswith(t) for t in territory):
        return CheckResult.BLOCK if rule.severity == RuleSeverity.MUST else CheckResult.WARN
    return CheckResult.PASS


def _check_sandbox(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    ca = get_config("constitution")
    if ca:
        modify_actions = frozenset(ca.get("modify_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_MODIFY_ACTIONS
        modify_actions = CONSTITUTION_MODIFY_ACTIONS
    if action in modify_actions:
        if rule.severity == RuleSeverity.MUST and target:
            # Real path check: verify target starts with configured sandbox root
            abs_target = _os.path.abspath(target)
            return CheckResult.PASS if abs_target.startswith(SANDBOX_ROOT_PATH) else CheckResult.WARN
        return CheckResult.PASS
    return CheckResult.PASS


def _check_constitution_mod(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    if not target:
        return CheckResult.PASS
    if CONSTITUTION_KEYWORD in target.lower():
        return CheckResult.BLOCK
    if target.endswith(CONSTITUTION_FILE_EXT):
        return CheckResult.BLOCK
    return CheckResult.PASS


def _check_gate(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    """G1 gate — tool whitelist check. Returns WARN (not BLOCK) for high-risk actions
    because GateChain G5 makes the final authorization decision based on reputation,
    history, and context. G1 only flags, it does not block."""
    ca = get_config("constitution")
    if ca:
        modify_actions = frozenset(ca.get("modify_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_MODIFY_ACTIONS
        modify_actions = CONSTITUTION_MODIFY_ACTIONS
    if action in CONSTITUTION_GATE_ACTIONS:
        return CheckResult.WARN
    return CheckResult.WARN if action in modify_actions and len(action) > CONSTITUTION_ACTION_LEN_THRESHOLD else CheckResult.PASS


def _check_scout(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    ca = get_config("constitution")
    if ca:
        file_actions = frozenset(ca.get("file_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_FILE_ACTIONS
        file_actions = CONSTITUTION_FILE_ACTIONS
    if agent_id == CONSTITUTION_SCOUT_AGENT_NAME:
        if action in CONSTITUTION_SCOUT_BLOCKED:
            return CheckResult.BLOCK
        if action in file_actions:
            return CheckResult.PASS
    return CheckResult.PASS


def _check_audit(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    return CheckResult.PASS


# Posture provider — injected at boot by L3 wiring (kernel never imports L3).
# Returns the ``get_posture()`` dict {security_mode, harness_mode,
# classification, full_power, ...} or None when not wired.
_posture_provider: Callable[[], dict | None] | None = None


def set_posture_provider(provider: Callable[[], dict | None] | None) -> None:
    """Register the posture provider callback (called at boot from L3 wiring).

    Eliminates the ``from l3.tool_system.security_mode import get_posture``
    import from the kernel layer — the provider is injected, not imported.
    """
    global _posture_provider
    _posture_provider = provider


def _check_skill_posture(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    """Constitutional gate: offensive-posture skills require attack posture.

    Applies to ``skill.use`` (session catalog) AND ``use_skill`` (the actual
    tool-pipeline action name) — an offensive skill is BLOCKED unless the
    injected posture provider reports full_power (attack classification +
    detection-bypass confirmed). ``skill.load`` (registration) is not blocked:
    offensive skills may exist in the registry but stay unusable — posture
    gating happens at use/injection. When no provider is wired, the rule
    passes (backward compatible).
    """
    if action not in ("skill.use", "use_skill"):
        return CheckResult.PASS
    provider = _posture_provider
    if provider is None:
        return CheckResult.PASS
    try:
        posture = provider() or {}
    except Exception:
        return CheckResult.PASS
    if posture.get("full_power"):
        return CheckResult.PASS
    # Not full power: block use of offensive-posture skills.
    try:
        from l1.kernel.skill import get_skill_manager

        skill = get_skill_manager().get(target)
        if skill and skill.get("posture") == SKILL_POSTURE_OFFENSIVE:
            return CheckResult.BLOCK
    except Exception:
        pass
    return CheckResult.PASS


def _check_cross(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
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
        tags=TAG_TERRITORY_WRITE,
    ),
    RuleDescriptor(
        id="territory.read_l3", section="§3.1",
        severity=RuleSeverity.MUST,
        description="Agent must not read files outside its territory without L3 approval",
        check_fn=_check_territory,
        tags=TAG_TERRITORY_READ,
    ),
    RuleDescriptor(
        id="gatechain.all", section="§3.3",
        severity=RuleSeverity.MUST,
        description="All tool calls must pass GateChain G1-G5",
        check_fn=_check_gate,
        tags=TAG_GATECHAIN,
    ),
    RuleDescriptor(
        id="gatechain.cross", section="§3.4",
        severity=RuleSeverity.MUST,
        description="Cross-unit tool calls require G5 approval",
        check_fn=_check_gate,
        tags=TAG_GATECHAIN_CROSS,
    ),
    RuleDescriptor(
        id="sandbox.writes", section="§4.5",
        severity=RuleSeverity.MUST,
        description="All modifications must go through sandbox (no direct writes)",
        check_fn=_check_sandbox,
        tags=TAG_SANDBOX,
    ),
    RuleDescriptor(
        id="sandbox.review", section="§4.6",
        severity=RuleSeverity.MUST,
        description="All modifications must be reviewable by L3 before flush",
        check_fn=_check_sandbox,
        tags=TAG_SANDBOX_REVIEW,
    ),
    RuleDescriptor(
        id="constitution.modify", section="§4.7",
        severity=RuleSeverity.MUST,
        description="No Agent may modify the constitution itself",
        check_fn=_check_constitution_mod,
        tags=TAG_CONSTITUTION,
    ),
    RuleDescriptor(
        id="audit.trail", section="§5.1",
        severity=RuleSeverity.MUST,
        description="All tool calls must be logged with audit trail",
        check_fn=_check_audit,
        tags=TAG_AUDIT,
    ),
    RuleDescriptor(
        id="decision.memory", section="§5.2",
        severity=RuleSeverity.SHOULD,
        description="All decisions must be recorded in memory Ring 2",
        check_fn=None,
        tags=TAG_MEMORY,
    ),
    RuleDescriptor(
        id="territory.cross_review", section="§6.1",
        severity=RuleSeverity.MUST,
        description="Cross-territory changes require peer review",
        check_fn=_check_cross,
        tags=TAG_TERRITORY_REVIEW,
    ),
    RuleDescriptor(
        id="l3.arbiter", section="§6.2",
        severity=RuleSeverity.MUST,
        description="L3 is the final arbiter of all disputes",
        check_fn=None,
        tags=TAG_L3,
    ),
    RuleDescriptor(
        id="scout.readonly", section="§7.1",
        severity=RuleSeverity.MUST,
        description="Scouts are read-only and depth=1",
        check_fn=_check_scout,
        tags=TAG_SCOUT,
    ),
    RuleDescriptor(
        id="scout.log", section="§7.2",
        severity=RuleSeverity.SHOULD,
        description="Scout findings must be logged before disposal",
        check_fn=_check_scout,
        tags=TAG_SCOUT_AUDIT,
    ),
    RuleDescriptor(
        id="ring.context", section="§8.1",
        severity=RuleSeverity.MUST,
        description="Agent context must be built from Ring memory, not raw output",
        check_fn=None,
        tags=TAG_MEMORY_RING,
    ),
    RuleDescriptor(
        id="ring.persist", section="§8.2",
        severity=RuleSeverity.SHOULD,
        description="Important decisions must be persisted to Ring 3 (long-term)",
        check_fn=None,
        tags=TAG_MEMORY_RING,
    ),
    RuleDescriptor(
        id="skill.builtin_readonly", section="§9.1",
        severity=RuleSeverity.MUST,
        description="Built-in (shipped) skills are read-only — no agent may modify or delete them",
        check_fn=None,
        tags=TAG_SKILL,
    ),
    RuleDescriptor(
        id="skill.offensive_posture", section="§9.2",
        severity=RuleSeverity.MUST,
        description="Offensive-posture skills require attack posture (full_power) for use",
        check_fn=_check_skill_posture,
        tags=TAG_SKILL,
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
        return TerritoryConstitution(source=CONSTITUTION_SOURCE_BLANK)
    return parse_territory(p.read_text(encoding="utf-8"), source=str(p))


# ── Scalar key setters (registration-style; extend by adding to _KEY_SETTERS) ──


def _set_default_reputation(c: TerritoryConstitution, value: str) -> None:
    """Parse the default_reputation scalar (float, 0..1)."""
    try:
        c.default_reputation = float(value)
    except Exception:
        logger.warning("constitution: invalid default_reputation: %s", value)


def _set_token_budget(c: TerritoryConstitution, value: str) -> None:
    """Parse the token_budget scalar (int)."""
    try:
        c.token_budget = int(value)
    except Exception:
        logger.warning("constitution: invalid token_budget: %s", value)


def _set_version(c: TerritoryConstitution, value: str) -> None:
    """Parse the version scalar (int)."""
    try:
        c.version = int(value)
    except Exception:
        logger.warning("constitution: invalid version: %s", value)


# Exact-key setters — registration-style dispatch (dict lookup, no elif chain).
_KEY_SETTERS: dict[str, Callable[[TerritoryConstitution, str], None]] = {
    "default_reputation": _set_default_reputation,
    "token_budget": _set_token_budget,
    "version": _set_version,
}


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
        else:
            setter = _KEY_SETTERS.get(key)
            if setter:
                setter(c, value)
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

    Rules can be hot-reloaded via reload() or updated at runtime via
    update_rules().  On BLOCK detection, emits NMI interrupt and
    EventBus signal for SSE broadcast to frontend.
    """

    def __init__(self):
        self._rules: list[RuleDescriptor] = list(_BUILTIN_DESCRIPTORS)
        self._lock = threading.Lock()
        self._constitution_path: str = ""
        self._cell_bus = None  # set by Cell to enable interrupt emission
        self._persist_handler: Callable[[list[dict], int], None] | None = None
        """Optional callback for persisting custom rules (set at boot to avoid L3 import)."""

    def set_persist_handler(self, handler: Callable[[list[dict], int], None]) -> None:
        """Register a callback to persist custom rules (called at boot from L3 wiring).

        Eliminates the ``from l3.config.settings_center import get_center``
        import from kernel layer.
        """
        self._persist_handler = handler

    # ── Cell bus binding (for constitution.violation NMI) ──

    def bind_cell(self, cell_bus: Any) -> None:
        """Bind a Cell bus so constitution violations trigger NMI interrupt.

        Called by Cell.__init__ after creating the cell bus.
        """
        self._cell_bus = cell_bus

    def _trigger_violation(self, action: str, agent_id: str,
                           target: str, rule_id: str) -> None:
        """Emit constitution.violation NMI via cell bus."""
        if not self._cell_bus:
            return
        try:
            self._cell_bus.emit("interrupt.triggered", {
                "irq": "constitution.violation",
                "data": {"action": action, "agent_id": agent_id,
                         "target": target, "rule_id": rule_id},
            })
        except Exception:
            logger.warning("constitution: cell bus emit failed — violation event lost")
        # Also emit EventBus signal for SSE broadcast
        try:
            from l1.kernel import get_event_bus  # lazy import avoids circular dep
            bus = get_event_bus()
            bus.emit_event("constitution.violation", data={
                "action": action, "agent_id": agent_id,
                "target": target, "rule_id": rule_id,
            })
        except Exception:
            logger.warning("constitution: event bus emit failed — violation event lost")

    # ── LLM-readable summary (injected into AgentLoop system prompt) ──

    def summary(self, for_agent: str = "") -> str:
        """Return a human-readable constitution summary for LLM context.

        Injected into AgentLoop's system prompt so the LLM knows
        the rules before making tool calls.  Filters rules relevant
        to the given agent if ``for_agent`` is provided.
        """
        with self._lock:
            must_rules = [r for r in self._rules
                          if r.severity == RuleSeverity.MUST]
            should_rules = [r for r in self._rules
                            if r.severity == RuleSeverity.SHOULD]

        lines = ["--- Constitution Rules ---"]
        lines.append("You MUST obey these rules. Violations will be blocked.")
        if must_rules:
            lines.append(f"\nMUST ({len(must_rules)} rules):")
            for r in must_rules:
                lines.append(f"  [{r.id}] {r.description}")
        if should_rules:
            lines.append(f"\nSHOULD ({len(should_rules)} rules):")
            for r in should_rules:
                lines.append(f"  [{r.id}] {r.description}")
        lines.append("\n--- End Constitution ---")
        return "\n".join(lines)

    # ── Hot-reload from file ──

    def load(self, path: str = "") -> dict:
        """Load constitution from .praxis-rules.md file."""
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
        # Emit loaded event for SSE
        try:
            from l1.kernel import get_event_bus
            get_event_bus().emit_event("constitution.loaded", data={
                "rules": len(self._rules), "custom": len(custom_rules), "path": path,
            })
        except Exception:
            logger.warning("constitution: failed to emit loaded event")
        return {"success": True, "rules": len(self._rules), "custom": len(custom_rules), "path": path}

    def reload(self) -> dict:
        """Reload constitution from the same file path (hot-reload)."""
        if not self._constitution_path:
            return {"success": False, "error": "no constitution path set"}
        return self.load(self._constitution_path)

    def update_rules(self, custom_rules: list[dict]) -> dict:
        """Add or update custom rules at runtime.

        Each rule dict:
          {"id": "...", "severity": "MUST|SHOULD|MAY",
           "description": "...", "section": "§custom"}

        Persists to SettingsCenter for L3 runtime overrides.
        """
        count = 0
        with self._lock:
            self._rules = [r for r in self._rules if r.source != "custom"]
            for spec in custom_rules:
                sev = _severity(spec.get("severity", "MUST"))
                self._rules.append(RuleDescriptor(
                    id=spec.get("id", f"custom.{len(self._rules)}"),
                    section=spec.get("section", CONSTITUTION_CUSTOM_SECTION),
                    severity=sev,
                    description=spec.get("description", ""),
                    source="custom",
                ))
                count += 1
        # Persist to SettingsCenter L3 (via registered callback, avoids direct import)
        if self._persist_handler:
            try:
                self._persist_handler(custom_rules, count)
            except Exception as e:
                logger.warning("constitution: persist handler failed: %s", e)
        else:
            logger.debug("constitution: no persist handler registered, custom rules not persisted")
        # Emit signal for SSE broadcast
        try:
            from l1.kernel import get_event_bus
            bus = get_event_bus()
            bus.emit_event("constitution.updated", data={"count": count})
        except Exception:
            logger.warning("constitution: failed to emit updated event")
        return {"success": True, "updated": count, "total": len(self._rules)}

    def clear_custom_rules(self) -> dict:
        """Remove all custom rules (keep built-in)."""
        with self._lock:
            self._rules = [r for r in self._rules if r.source != "custom"]
        return {"success": True, "total": len(self._rules)}

    def rules_list(self) -> list[dict]:
        """Return a summary dict for every loaded rule."""
        with self._lock:
            return [{"id": r.id, "section": r.section,
                     "severity": r.severity.name,
                     "description": r.description,
                     "source": r.source or "builtin"}
                    for r in self._rules]

    # ── Enhanced check with violation event emission ──

    def check(self, action: str, agent_id: str, target: str = "",
              territory: list[str] | None = None) -> list[CheckReport]:
        """Evaluate all rules for an action and return non-pass reports."""
        reports: list[CheckReport] = []
        for rule in self._rules:
            result = self._evaluate(rule, action, agent_id, target, territory or [])
            if result == CheckResult.BLOCK:
                self._trigger_violation(action, agent_id, target, rule.id)
            if result != CheckResult.PASS:
                reports.append(CheckReport(rule=rule, result=result,
                                           detail=self._describe(rule, action, agent_id, target)))
        return reports

    def is_allowed(self, action: str, agent_id: str, target: str = "",
                   territory: list[str] | None = None) -> dict:
        """Check whether the action is allowed; return decision details."""
        reports = self.check(action, agent_id, target, territory)
        blocks = [r for r in reports if r.result == CheckResult.BLOCK]
        return {
            "allowed": len(blocks) == 0,
            "decision": "pass" if not blocks else "block",
            "blocks": len(blocks),
            "warns": len([r for r in reports if r.result == CheckResult.WARN]),
            "details": [{"section": r.rule.section, "rule_id": r.rule.id,
                         "result": r.result.name, "detail": r.detail}
                        for r in reports],
        }

    def to_dict(self) -> dict:
        """Full constitution state for API export."""
        with self._lock:
            return {
                "path": self._constitution_path or "",
                "total_rules": len(self._rules),
                "builtin": len([r for r in self._rules if r.source != "custom"]),
                "custom": len([r for r in self._rules if r.source == "custom"]),
                "rules": [{"id": r.id, "section": r.section,
                           "severity": r.severity.name,
                           "description": r.description,
                           "source": r.source or "builtin"}
                          for r in self._rules],
            }

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
_constitution_lock = threading.Lock()


def get_constitution() -> Constitution:
    """Get the Constitution engine singleton."""
    global _constitution
    if _constitution is None:
        with _constitution_lock:
            if _constitution is None:
                _constitution = Constitution()
    return _constitution


def reset_constitution() -> None:
    """Reset the Constitution singleton for testing."""
    global _constitution
    _constitution = None
