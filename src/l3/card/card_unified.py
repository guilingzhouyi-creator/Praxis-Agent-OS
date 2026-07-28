"""CardUnified — single unified card model for the entire Agent OS.

Replaces the fragmented card types (Card, CardRecord, TaskCard, etc.)
with one universal data model that covers all card natures.

Architecture:
  CardTypeDef      — config-driven card type definition (YAML-extensible)
  CardUnified      — the universal card instance
  CardSummary      — multi-column expandable summary area
  CardPhase        — execution phase (single or multi-Peer-Agent)
  CardTask         — task within a phase
  CardTimestamps   — hidden auto-managed lifecycle timestamps
  CardModification — hidden versioned modification trail

Card lifecycle:
  DRAFT → QUEUED → DISPATCHED → RUNNING → COMPLETED | FAILED | CANCELLED
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.params.system import HASH_TRUNC_SHORT, LOG_TRUNC_80, LOG_TRUNC_200, LOG_TRUNC_500

logger = logging.getLogger(__name__)


# ── Lifecycle ──

class CardLifecycle(Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Phase execution mode ──

class PhaseMode(Enum):
    SINGLE = "single"       # one agent handles all tasks
    MULTI = "multi"         # tasks distributed to multiple agents


# ── Card type definition (config-driven, YAML-extensible) ──

_card_type_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()


def register_card_type(name: str, definition: dict) -> None:
    """Register a card type definition.

    YAML example:
      card_types:
        execution:
          display: "Execution Card"
          has_review: true
          phases: ["plan", "implement", "review"]
        issue:
          display: "Issue Card"
          has_review: false
          phases: ["discuss", "converge"]
    """
    with _registry_lock:
        _card_type_registry[name] = {
            "display": definition.get("display", name),
            "has_review": definition.get("has_review", False),
            "phases": list(definition.get("phases", [])),
            "default_prompts": dict(definition.get("default_prompts", {})),
            "metadata_schema": dict(definition.get("metadata_schema", {})),
        }


def get_card_type(name: str) -> dict:
    with _registry_lock:
        return _card_type_registry.get(name, {})


def list_card_types() -> list[dict]:
    with _registry_lock:
        return [
            {"name": k, **v}
            for k, v in _card_type_registry.items()
        ]


def load_card_types(cfg: dict) -> None:
    """Load card type definitions from praxis.yaml → card_types: section."""
    if not cfg:
        return
    for name, defn in cfg.items():
        register_card_type(name, defn)


# ── Summary: multi-column expandable metadata ──

@dataclass
class CardSummary:
    title: str = ""
    description: str = ""
    columns: dict[str, str] = field(default_factory=dict)
    # columns = {"Domain": "app/auth", "Risk": "low", "Files": "3", ...}

    def set_column(self, key: str, value: str) -> None:
        self.columns[key] = value

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description[:LOG_TRUNC_500],
            "columns": dict(self.columns),
        }


# ── Task ──

@dataclass
class CardTask:
    action: str = ""
    target: str = ""
    params: dict = field(default_factory=dict)
    agent: str = ""          # resolved agent_id; "" = auto-assign
    state: str = "pending"   # pending | running | done | failed | skipped
    result: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "target": self.target,
            "agent": self.agent,
            "state": self.state,
            "error": self.error[:LOG_TRUNC_80] if self.error else "",
        }


# ── Phase ──

@dataclass
class CardPhase:
    name: str = ""
    mode: PhaseMode = PhaseMode.SINGLE
    agents: list[str] = field(default_factory=list)  # assigned agents; empty=auto
    tasks: list[CardTask] = field(default_factory=list)
    review_prompt: str = ""   # configurable, from YAML or API
    state: str = "pending"    # pending | running | done | failed

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mode": self.mode.value,
            "agents": list(self.agents),
            "state": self.state,
            "tasks": [t.to_dict() for t in self.tasks],
            "has_review_prompt": bool(self.review_prompt),
        }


# ── Timestamps (hidden, auto-managed) ──

@dataclass
class CardTimestamps:
    created_at: float = field(default_factory=time.time)      # L3A creates card
    submitted_at: float = 0.0    # registered in queue
    dispatched_at: float = 0.0   # sent to Cell
    completed_at: float = 0.0    # all phases done

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "submitted_at": self.submitted_at,
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
        }


# ── Modification record (hidden, versioned) ──

@dataclass
class CardModification:
    version: int = 0
    timestamp: float = 0.0
    field: str = ""            # "summary.title", "phases[0].tasks", "priority", etc.
    old_value: Any = None
    new_value: Any = None

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "field": self.field,
            "old_preview": str(self.old_value)[:LOG_TRUNC_200] if self.old_value else "",
            "new_preview": str(self.new_value)[:LOG_TRUNC_200] if self.new_value else "",
        }


# ── Unified Card ──

@dataclass
class CardUnified:
    id: str = field(default_factory=lambda: f"card-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}")
    nature: str = "execution"           # card type name from registry
    priority: int = 5                   # 1-10, 1=highest
    state: CardLifecycle = CardLifecycle.DRAFT
    summary: CardSummary = field(default_factory=CardSummary)
    phases: list[CardPhase] = field(default_factory=list)
    error: str = ""

    # ── Hidden system fields ──
    timestamps: CardTimestamps = field(default_factory=CardTimestamps)
    modifications: list[CardModification] = field(default_factory=list)
    _completion_summary: str = ""
    _changes: list[dict] = field(default_factory=list)   # actual file/system changes
    _depends_on: list[str] = field(default_factory=list)  # dependency card IDs

    # ── Modification tracking ──

    def _track_mod(self, field: str, old: Any, new: Any) -> None:
        self.modifications.append(CardModification(
            version=len(self.modifications) + 1,
            timestamp=time.time(),
            field=field,
            old_value=old,
            new_value=new,
        ))

    def set_nature(self, nature: str) -> None:
        old = self.nature
        self.nature = nature
        self._track_mod("nature", old, nature)

    def set_priority(self, priority: int) -> None:
        old = self.priority
        self.priority = max(1, min(10, priority))
        self._track_mod("priority", old, self.priority)

    def set_summary_column(self, key: str, value: str) -> None:
        old = self.summary.columns.get(key, "")
        self.summary.set_column(key, value)
        self._track_mod(f"summary.columns.{key}", old, value)

    def update_title(self, title: str) -> None:
        old = self.summary.title
        self.summary.title = title
        self._track_mod("summary.title", old, title)

    # ── Lifecycle ──

    def submit(self) -> None:
        """Mark as queued, set submission timestamp."""
        self.state = CardLifecycle.QUEUED
        self.timestamps.submitted_at = time.time()

    def dispatch(self) -> None:
        """Mark as dispatched to Cell."""
        self.state = CardLifecycle.DISPATCHED
        self.timestamps.dispatched_at = time.time()

    def complete(self, summary: str = "", changes: list[dict] | None = None) -> None:
        self.state = CardLifecycle.COMPLETED
        self.timestamps.completed_at = time.time()
        self._completion_summary = summary
        if changes:
            self._changes = changes

    def fail(self, error: str) -> None:
        self.state = CardLifecycle.FAILED
        self.timestamps.completed_at = time.time()
        self.error = error

    # ── Old-model bridge ──

    def to_old_card(self):
        """Convert CardUnified → old Card (card.py) for backward compat.

        Used during the Phase 1→2 migration so that existing
        ExecutionPlan / cell.execute_card() can consume CardUnified
        without being rewritten all at once.
        """
        from .models import Card as OldCard, CardMode as OldCardMode
        from .models import Phase as OldPhase, PhaseMode as OldPhaseMode
        from .models import Step as OldStep

        # Map nature → CardMode
        mode_map = {
            "execution": OldCardMode.EXECUTE,
            "issue": OldCardMode.ISSUE,
            "parallel_all": OldCardMode.PARALLEL_ALL,
        }
        old_mode = mode_map.get(self.nature, OldCardMode.EXECUTE)

        # Map PhaseMode
        phase_mode_map = {
            PhaseMode.SINGLE: OldPhaseMode.SEQUENTIAL,
            PhaseMode.MULTI: OldPhaseMode.PARALLEL,
        }

        old_phases = []
        for phase in self.phases:
            old_steps = []
            for task in phase.tasks:
                old_steps.append(OldStep(
                    action=task.action,
                    target=task.target,
                    params=dict(task.params),
                    agent=task.agent,
                ))
            old_mode_phase = phase_mode_map.get(phase.mode, OldPhaseMode.SEQUENTIAL)
            old_phases.append(OldPhase(
                name=phase.name,
                steps=old_steps,
                mode=old_mode_phase,
            ))

        domain = self.summary.columns.get("domain", self.nature)
        cell_id = self.summary.columns.get("cell_id", "")
        return OldCard(
            id=self.id,
            intent=self.summary.title,
            domain=domain,
            mode=old_mode,
            phases=old_phases,
            priority=self.priority,
            sender="l3",
            cell_id=cell_id,
        )

    # ── Phase management ──

    def add_phase(self, name: str, mode: PhaseMode = PhaseMode.SINGLE,
                  agents: list[str] | None = None,
                  review_prompt: str = "") -> CardPhase:
        phase = CardPhase(
            name=name, mode=mode,
            agents=agents or [],
            review_prompt=review_prompt,
        )
        self.phases.append(phase)
        self._track_mod(f"phases.add", None, name)
        return phase

    def add_task(self, phase_name: str, action: str, target: str = "",
                 params: dict | None = None, agent: str = "") -> CardTask | None:
        for phase in self.phases:
            if phase.name == phase_name:
                task = CardTask(action=action, target=target,
                                params=params or {}, agent=agent)
                phase.tasks.append(task)
                return task
        return None

    def resolve_agents(self, agent_map: dict[str, str],
                       default_agent: str = "") -> None:
        """Resolve role → agent_id for all phases and tasks.

        Single mode: all tasks go to the first available agent.
        Multi mode: tasks are distributed by their agent field.
        If a phase has no agents specified, auto-assign by round-robin
        or first-available from agent_map.
        """
        used_agents = list(agent_map.values()) if agent_map else []
        for phase in self.phases:
            if phase.mode == PhaseMode.SINGLE:
                agent = (phase.agents[0] if phase.agents
                         else used_agents[0] if used_agents
                         else default_agent)
                phase.agents = [agent] if agent else phase.agents
                for task in phase.tasks:
                    task.agent = agent
            else:  # MULTI
                if not phase.agents:
                    phase.agents = list(used_agents)
                for i, task in enumerate(phase.tasks):
                    if not task.agent and phase.agents:
                        task.agent = phase.agents[i % len(phase.agents)]

    # ── Review ──

    def needs_review(self) -> bool:
        td = get_card_type(self.nature)
        return td.get("has_review", False) if td else False

    def review_phases(self) -> list[CardPhase]:
        return [p for p in self.phases if p.review_prompt]

    # ── Serialization ──

    def to_dict(self, include_hidden: bool = False) -> dict:
        base = {
            "id": self.id,
            "nature": self.nature,
            "priority": self.priority,
            "state": self.state.value,
            "summary": self.summary.to_dict(),
            "phases": [p.to_dict() for p in self.phases],
            "error": self.error[:LOG_TRUNC_80] if self.error else "",
        }
        if include_hidden:
            base["timestamps"] = self.timestamps.to_dict()
            base["modifications"] = [m.to_dict() for m in self.modifications]
            base["_completion_summary"] = self._completion_summary[:LOG_TRUNC_500]
            base["_changes"] = list(self._changes)[-20:]
        return base

    def to_persist(self) -> dict:
        """Full serialization for persistence (includes hidden fields)."""
        return {
            "card_version": 1,
            "id": self.id,
            "nature": self.nature,
            "priority": self.priority,
            "state": self.state.value,
            "summary": {
                "title": self.summary.title,
                "description": self.summary.description,
                "columns": dict(self.summary.columns),
            },
            "phases": [{
                "name": p.name, "mode": p.mode.value,
                "agents": list(p.agents), "state": p.state,
                "review_prompt": p.review_prompt,
                "tasks": [{
                    "action": t.action, "target": t.target,
                    "params": dict(t.params),
                    "agent": t.agent, "state": t.state,
                    "error": t.error,
                } for t in p.tasks],
            } for p in self.phases],
            "error": self.error,
            "timestamps": {
                "created_at": self.timestamps.created_at,
                "submitted_at": self.timestamps.submitted_at,
                "dispatched_at": self.timestamps.dispatched_at,
                "completed_at": self.timestamps.completed_at,
            },
            "depends_on": list(self._depends_on),
            "modifications": [{
                "version": m.version, "timestamp": m.timestamp,
                "field": m.field,
            } for m in self.modifications],
            "_completion_summary": self._completion_summary,
            "_changes": list(self._changes)[-50:],
        }

    @staticmethod
    def from_persist(data: dict) -> CardUnified:
        card = CardUnified(
            id=data.get("id", ""),
            nature=data.get("nature", "execution"),
            priority=data.get("priority", 5),
            state=CardLifecycle(data.get("state", "draft")),
            error=data.get("error", ""),
        )
        s = data.get("summary", {})
        card.summary = CardSummary(
            title=s.get("title", ""),
            description=s.get("description", ""),
            columns=dict(s.get("columns", {})),
        )
        for pd in data.get("phases", []):
            phase = CardPhase(
                name=pd.get("name", ""),
                mode=PhaseMode(pd.get("mode", "single")),
                agents=list(pd.get("agents", [])),
                state=pd.get("state", "pending"),
                review_prompt=pd.get("review_prompt", ""),
            )
            for td in pd.get("tasks", []):
                phase.tasks.append(CardTask(
                    action=td.get("action", ""),
                    target=td.get("target", ""),
                    params=dict(td.get("params", {})),
                    agent=td.get("agent", ""),
                    state=td.get("state", "pending"),
                    error=td.get("error", ""),
                ))
            card.phases.append(phase)
        ts = data.get("timestamps", {})
        card.timestamps = CardTimestamps(
            created_at=ts.get("created_at", 0.0),
            submitted_at=ts.get("submitted_at", 0.0),
            dispatched_at=ts.get("dispatched_at", 0.0),
            completed_at=ts.get("completed_at", 0.0),
        )
        card._depends_on = list(data.get("depends_on", []))
        for md in data.get("modifications", []):
            card.modifications.append(CardModification(
                version=md.get("version", 0),
                timestamp=md.get("timestamp", 0.0),
                field=md.get("field", ""),
            ))
        card._completion_summary = data.get("_completion_summary", "")
        card._changes = list(data.get("_changes", []))
        return card


# ── Built-in card type registration ──

def _register_builtins() -> None:
    register_card_type("execution", {
        "display": "Execution Card",
        "has_review": True,
        "phases": ["plan", "implement", "review"],
        "default_prompts": {
            "review": "Verify all changes implement the intent correctly.",
        },
        "metadata_schema": {
            "domain": {"type": "string", "default": "."},
            "risk": {"type": "choice", "options": ["low", "medium", "high"]},
        },
    })
    register_card_type("issue", {
        "display": "Issue Card",
        "has_review": False,
        "phases": ["discuss", "converge"],
        "default_prompts": {},
        "metadata_schema": {
            "domain": {"type": "string", "default": "."},
        },
    })
    register_card_type("review", {
        "display": "Review Card",
        "has_review": True,
        "phases": ["review"],
        "default_prompts": {
            "review": "Review the code for correctness, security, and style.",
        },
        "metadata_schema": {},
    })
    register_card_type("inspection", {
        "display": "Inspection Card",
        "has_review": False,
        "phases": ["inspect"],
        "default_prompts": {},
        "metadata_schema": {
            "target": {"type": "string"},
        },
    })


_register_builtins()
