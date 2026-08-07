"""Card Builder — converts raw intent into structured Card with phases, tasks.

L3A parses a TaskCard → CardBuilder → structured CardUnified (Phase/Task)

Auto-generates the appropriate workflow based on intent and domain:

  "build project"     →  lint → test → build → verify
  "refactor login"    →  scout → plan → modify → verify
  "add feature"       →  scout → design → implement → test → verify
  "fix bug"           →  scout → diagnose → fix → verify
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from l1.kernel.params.agent import CARD_BUILDER_MODES
from l1.kernel.params.system import HASH_TRUNC_SHORT, LOG_TRUNC_40, LOG_TRUNC_80

from .card_unified import CardPhase, CardSummary, CardTask, CardUnified, PhaseMode

logger = logging.getLogger(__name__)


# ── Helpers ──


def _phase_mode(name: str) -> PhaseMode:
    """Map CARD_BUILDER_MODES config flag to PhaseMode.

    Config values 'SEQUENTIAL' or absent → PhaseMode.SINGLE
    Config values 'PARALLEL' → PhaseMode.MULTI
    """
    mode_str = CARD_BUILDER_MODES.get(name, "EXECUTE")
    return PhaseMode.MULTI if mode_str in ("PARALLEL", "PARALLEL_ALL") else PhaseMode.SINGLE


def _build_card_unified(card_id: str, intent: str, domain: str, priority: int, phases: list[CardPhase]) -> CardUnified:
    card = CardUnified(id=card_id, priority=priority, nature="execution", phases=phases)
    card.summary = CardSummary(title=intent, description="", columns={"domain": domain or "."})
    return card


# ── Detector registry ──


def register_detector(name: str, patterns: list[str], builder: Callable) -> None:
    """Register a card type detector. Extensible — call before build_card()."""
    _DETECTORS.append({"name": name, "patterns": [p.lower() for p in patterns], "builder": builder})


def register_detectors_from_config(config: list[dict]) -> None:
    """Load detectors from a config list (e.g., from praxis.yaml)."""
    for entry in config:
        name = entry.get("name", "")
        patterns = entry.get("patterns", [])
        builder_name = entry.get("builder", "")
        builder = _BUILDER_MAP.get(builder_name) or _BUILDER_MAP.get(name)
        if patterns and builder:
            register_detector(name, patterns, builder)


def build_card(task_id: str, intent: str, domain: str = "", priority: int = 5) -> CardUnified:
    """Convert a TaskCard intent into a structured CardUnified.

    Uses registered detectors in order. First match wins.
    Extensible: call register_detector() to add custom card types.
    """
    intent_lower = intent.lower()
    card_id = task_id or f"card-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"

    for det in _DETECTORS:
        if any(p in intent_lower for p in det["patterns"]):
            return det["builder"](card_id, intent, domain, priority)
    return _build_default_card(card_id, intent, domain, priority)


# Built-in detectors
DETECTOR_CONFIG: list[dict] = [
    {"name": "build", "patterns": ["build", "compile", "make", "ci", "deploy", "dist"]},
    {"name": "fix", "patterns": ["fix", "bug", "error", "crash", "hotfix", "patch"]},
    {"name": "refactor", "patterns": ["refactor", "clean", "rename", "extract", "modularize"]},
    {"name": "feature", "patterns": ["add", "feature", "implement", "create", "new"]},
    {"name": "review", "patterns": ["review", "audit", "inspect", "check"]},
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


def _step(action: str, target: str = "", agent: str = "default", params: dict | None = None) -> CardTask:
    """Shorthand for CardTask construction."""
    return CardTask(action=action, target=target, agent=agent, params=params or {})


def _phase(name: str, tasks: list[CardTask], mode: PhaseMode = PhaseMode.SINGLE) -> CardPhase:
    """Shorthand for CardPhase construction."""
    return CardPhase(name=name, mode=mode, tasks=tasks)


# ── Builder functions ──


def _build_build_card(card_id: str, intent: str, domain: str, priority: int) -> CardUnified:
    """Build card: lint → test → build → verify."""
    path = domain or "."
    return _build_card_unified(
        card_id,
        intent,
        domain,
        priority,
        [
            _phase(
                "lint",
                [
                    _step(
                        "scout",
                        "grep",
                        agent="scout",
                        params={"template": "grep", "pattern": "TODO|FIXME|HACK|XXX", "path": path},
                    ),
                ],
            ),
            _phase(
                "build",
                [
                    _step("think", f"build {path}"),
                    _step("think", f"verify build {path}"),
                ],
                mode=PhaseMode.MULTI,
            ),
        ],
    )


def _build_fix_card(card_id: str, intent: str, domain: str, priority: int) -> CardUnified:
    """Fix card: scout → diagnose → fix → verify."""
    return _build_card_unified(
        card_id,
        intent,
        domain,
        priority,
        [
            _phase(
                "investigate",
                [
                    _step(
                        "scout",
                        "grep",
                        agent="scout",
                        params={"template": "grep", "pattern": "error|fail|exception", "path": domain or "."},
                    ),
                    _step("scout", "structure", agent="scout", params={"template": "structure", "path": domain or "."}),
                ],
                mode=PhaseMode.MULTI,
            ),
            _phase(
                "diagnose",
                [
                    _step("think", f"diagnose {intent[:LOG_TRUNC_40]}"),
                ],
            ),
            _phase(
                "fix",
                [
                    _step("think", f"fix {domain}"),
                ],
            ),
        ],
    )


def _build_refactor_card(card_id: str, intent: str, domain: str, priority: int) -> CardUnified:
    """Refactor card: scout → plan → modify → verify."""
    return _build_card_unified(
        card_id,
        intent,
        domain,
        priority,
        [
            _phase(
                "investigate",
                [
                    _step(
                        "scout",
                        "grep",
                        agent="scout",
                        params={"template": "grep", "pattern": "magic.number|hardcode|TODO", "path": domain or "."},
                    ),
                    _step("scout", "summary", agent="scout", params={"template": "summary", "path": domain or "."}),
                ],
                mode=PhaseMode.MULTI,
            ),
            _phase(
                "plan",
                [
                    _step("think", f"refactor plan for {domain}"),
                ],
            ),
            _phase(
                "modify",
                [
                    _step("think", f"apply refactor {domain}"),
                    _step("think", f"verify refactor {domain}"),
                ],
                mode=PhaseMode.MULTI,
            ),
        ],
    )


def _build_feature_card(card_id: str, intent: str, domain: str, priority: int) -> CardUnified:
    """Feature card: scout → design → implement → test → verify."""
    return _build_card_unified(
        card_id,
        intent,
        domain,
        priority,
        [
            _phase(
                "scout",
                [
                    _step("scout", "structure", agent="scout", params={"template": "structure", "path": domain or "."}),
                    _step("scout", "read", agent="scout", params={"template": "read", "path": f"{domain or '.'}/"}),
                ],
                mode=PhaseMode.MULTI,
            ),
            _phase(
                "implement",
                [
                    _step("think", f"implement {intent[:LOG_TRUNC_40]}"),
                    _step("think", f"review {domain}"),
                ],
                mode=PhaseMode.MULTI,
            ),
        ],
    )


def _build_review_card(card_id: str, intent: str, domain: str, priority: int) -> CardUnified:
    """Review card: scout security → scout style → review → report."""
    return _build_card_unified(
        card_id,
        intent,
        domain,
        priority,
        [
            _phase(
                "scan",
                [
                    _step(
                        "scout",
                        "grep",
                        agent="scout",
                        params={"template": "grep", "pattern": "password|secret|key|token", "path": domain or "."},
                    ),
                    _step("scout", "summary", agent="scout", params={"template": "summary", "path": domain or "."}),
                ],
                mode=PhaseMode.MULTI,
            ),
            _phase(
                "report",
                [
                    _step("think", f"review report for {domain}"),
                ],
            ),
        ],
    )


def _build_default_card(card_id: str, intent: str, domain: str, priority: int) -> CardUnified:
    return _build_card_unified(
        card_id,
        intent,
        domain,
        priority,
        [
            _phase(
                "execute",
                [
                    _step("think", intent[:LOG_TRUNC_80]),
                ],
            ),
        ],
    )


# Initialize detector registry (after all builder functions are defined)
_init_detectors()
