"""Card Builder — converts raw intent into structured Card with phases, steps, and verify chains.

L3A parses a TaskCard → CardBuilder → structured Card (Phase/Step/verify)

Auto-generates the appropriate workflow based on intent and domain:

  "build project"     →  lint → test → build → verify
  "refactor login"    →  scout → plan → modify → verify
  "add feature"       →  scout → design → implement → test → verify
  "fix bug"           →  scout → diagnose → fix → verify
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from .card import Card, CardMode, Phase, PhaseMode, Step
from kernel.params import CARD_BUILDER_MODES

logger = logging.getLogger(__name__)

def _get_builder_mode(name: str) -> CardMode:
    """Get CardMode for a builder function from config (CARD_BUILDER_MODES)."""
    mode_str = CARD_BUILDER_MODES.get(name, 'EXECUTE')
    return getattr(CardMode, mode_str, CardMode.EXECUTE)




def register_detector(name: str, patterns: list[str],
                       builder: Callable) -> None:
    """Register a card type detector. Extensible — call before build_card()."""
    _DETECTORS.append({"name": name, "patterns": [p.lower() for p in patterns],
                        "builder": builder})


def register_detectors_from_config(config: list[dict]) -> None:
    """Load detectors from a config list (e.g., from praxis.yaml)."""
    for entry in config:
        name = entry.get("name", "")
        patterns = entry.get("patterns", [])
        builder_name = entry.get("builder", "")
        builder = _BUILDER_MAP.get(builder_name) or _BUILDER_MAP.get(name)
        if patterns and builder:
            register_detector(name, patterns, builder)


def build_card(task_id: str, intent: str, domain: str = "",
               priority: int = 5) -> Card:
    """Convert a TaskCard intent into a structured Card.

    Uses registered detectors in order. First match wins.
    Extensible: call register_detector() to add custom card types.
    """
    intent_lower = intent.lower()
    card_id = task_id or f"card-{uuid.uuid4().hex[:8]}"

    for det in _DETECTORS:
        if any(p in intent_lower for p in det["patterns"]):
            return det["builder"](card_id, intent, domain, priority)
    return _build_default_card(card_id, intent, domain, priority)


# Built-in detectors
DETECTOR_CONFIG: list[dict] = [
    {"name": "build",    "patterns": ["build", "compile", "make", "ci", "deploy", "dist"]},
    {"name": "fix",      "patterns": ["fix", "bug", "error", "crash", "hotfix", "patch"]},
    {"name": "refactor", "patterns": ["refactor", "clean", "rename", "extract", "modularize"]},
    {"name": "feature",  "patterns": ["add", "feature", "implement", "create", "new"]},
    {"name": "review",   "patterns": ["review", "audit", "inspect", "check"]},
]

_BUILDER_MAP: dict[str, Callable] = {}

_DETECTORS: list[dict] = []


def _init_detectors() -> None:
    for cfg in DETECTOR_CONFIG:
        name = cfg["name"]
        fn = globals().get(f"_build_{name}_card")
        if fn:
            _BUILDER_MAP[name] = fn
            register_detector(name, cfg["patterns"], fn)


def _build_build_card(card_id: str, intent: str, domain: str,
                      priority: int) -> Card:
    """Build card: lint → test → build → verify.

    Engineering conventions enforced at every phase.
    """
    path = domain or "."
    return Card(
        id=card_id, intent=intent, domain=domain,
        mode=_get_builder_mode("build_audit"),
        priority=priority,
        phases=[
            Phase(name="lint", mode=PhaseMode.SEQUENTIAL, steps=[
                Step(action="scout", target="grep",
                     params={"template": "grep",
                             "pattern": "TODO|FIXME|HACK|XXX",
                             "path": path},
                     agent="scout",
                     verify={"template": "grep",
                             "scope": {"pattern": "TODO|FIXME", "path": path}}),
            ]),
            Phase(name="build", mode=PhaseMode.PARALLEL, steps=[
                Step(action="think", target=f"build {path}", agent="default"),
                Step(action="think", target=f"verify build {path}", agent="default",
                     verify={"template": "grep",
                             "scope": {"pattern": "error|failed", "path": path}}),
            ]),
        ],
    )


def _build_fix_card(card_id: str, intent: str, domain: str,
                    priority: int) -> Card:
    """Fix card: scout → diagnose → fix → verify."""
    return Card(
        id=card_id, intent=intent, domain=domain,
        mode=_get_builder_mode("build_document"),
        priority=priority,
        phases=[
            Phase(name="investigate", mode=PhaseMode.PARALLEL, steps=[
                Step(action="scout", target="grep",
                     params={"template": "grep",
                             "pattern": "error|fail|exception",
                             "path": domain or "."},
                     agent="scout"),
                Step(action="scout", target="structure",
                     params={"template": "structure", "path": domain or "."},
                     agent="scout"),
            ]),
            Phase(name="diagnose", mode=PhaseMode.SEQUENTIAL, steps=[
                Step(action="think", target=f"diagnose {intent[:40]}", agent="default"),
            ]),
            Phase(name="fix", mode=PhaseMode.SEQUENTIAL, steps=[
                Step(action="think", target=f"fix {domain}", agent="default",
                     verify={"template": "grep",
                             "scope": {"pattern": "error|fail|exception",
                                       "path": domain or "."}}),
            ]),
        ],
    )


def _build_refactor_card(card_id: str, intent: str, domain: str,
                         priority: int) -> Card:
    """Refactor card: scout → plan → modify → verify."""
    return Card(
        id=card_id, intent=intent, domain=domain,
        mode=_get_builder_mode("build_redesign"),
        priority=priority,
        phases=[
            Phase(name="investigate", mode=PhaseMode.PARALLEL, steps=[
                Step(action="scout", target="grep",
                     params={"template": "grep",
                             "pattern": "magic.number|hardcode|TODO",
                             "path": domain or "."},
                     agent="scout"),
                Step(action="scout", target="summary",
                     params={"template": "summary", "path": domain or "."},
                     agent="scout"),
            ]),
            Phase(name="plan", mode=PhaseMode.SEQUENTIAL, steps=[
                Step(action="think", target=f"refactor plan for {domain}", agent="default"),
            ]),
            Phase(name="modify", mode=PhaseMode.PARALLEL, steps=[
                Step(action="think", target=f"apply refactor {domain}", agent="default"),
                Step(action="think", target=f"verify refactor {domain}", agent="default",
                     verify={"template": "grep",
                             "scope": {"pattern": "magic.number|hardcode",
                                       "path": domain or "."}}),
            ]),
        ],
    )


def _build_feature_card(card_id: str, intent: str, domain: str,
                        priority: int) -> Card:
    """Feature card: scout → design → implement → test → verify."""
    return Card(
        id=card_id, intent=intent, domain=domain,
        mode=_get_builder_mode("build_refactor"),
        priority=priority,
        phases=[
            Phase(name="scout", mode=PhaseMode.PARALLEL, steps=[
                Step(action="scout", target="structure",
                     params={"template": "structure", "path": domain or "."},
                     agent="scout"),
                Step(action="scout", target="read",
                     params={"template": "read", "path": f"{domain or '.'}/"},
                     agent="scout"),
            ]),
            Phase(name="implement", mode=PhaseMode.PARALLEL, steps=[
                Step(action="think", target=f"implement {intent[:40]}", agent="default"),
                Step(action="think", target=f"review {domain}", agent="default",
                     verify={"template": "grep",
                             "scope": {"pattern": "TODO|FIXME",
                                       "path": domain or "."}}),
            ]),
        ],
    )


def _build_review_card(card_id: str, intent: str, domain: str,
                       priority: int) -> Card:
    """Review card: scout security → scout style → review → report."""
    return Card(
        id=card_id, intent=intent, domain=domain,
        mode=_get_builder_mode("build_subtask"),
        priority=priority,
        phases=[
            Phase(name="scan", mode=PhaseMode.PARALLEL, steps=[
                Step(action="scout", target="grep",
                     params={"template": "grep",
                             "pattern": "password|secret|key|token",
                             "path": domain or "."},
                     agent="scout"),
                Step(action="scout", target="summary",
                     params={"template": "summary", "path": domain or "."},
                     agent="scout"),
            ]),
            Phase(name="report", mode=PhaseMode.SEQUENTIAL, steps=[
                Step(action="think", target=f"review report for {domain}", agent="default"),
            ]),
        ],
    )


def _build_default_card(card_id: str, intent: str, domain: str,
                        priority: int) -> Card:
    return Card(
        id=card_id, intent=intent, domain=domain,
        mode=_get_builder_mode("build_repair"),
        priority=priority,
        phases=[
            Phase(name="execute", steps=[
                Step(action="think", target=intent[:80], agent="default"),
            ]),
        ],
    )


# Initialize detector registry (after all builder functions are defined)
_init_detectors()
