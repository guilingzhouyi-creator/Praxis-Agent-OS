"""Skill system — loadable agent capabilities.

Skills are YAML/Markdown files that define:
  - Knowledge: architecture, conventions, domain expertise
  - Rules: coding standards, review criteria, testing requirements
  - Procedures: step-by-step workflows

Skills are mounted in VFS at /skills/ and agents can query them.

Usage:
  from l1.kernel.skill import get_skill_manager
  sm = get_skill_manager()
  sm.load("python_style")
  sm.get("python_style")  # → {"name": "...", "rules": [...]}
  sm.list_skills()               # → all loaded skills
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Final

from l1.kernel.params.agent import (
    AGENT_CLEARANCE,
    R4_CONTRIB_MIN_RATIO,
    R4_CONTRIB_MIN_TRIALS,
    R4_CURATION_ENABLED,
    R4_DISTILL_ENABLED,
    R4_DISTILL_SUB_CLUSTERING,
    R4_DISTILL_SUB_GENERALIZE,
    R4_DISTILL_SUB_LLM,
    R4_DISTILL_SUB_SAMPLING,
    R4_DPO_SIGNAL_ENABLED,
    R4_RETRIEVAL_ENABLED,
    R4_RETRIEVAL_MIN_SCORE,
)
from l1.kernel.params.system import (
    LOG_TRUNC_50,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
    SKILL_AUDIENCE_FILTER_ENABLED,
    SKILL_CATALOG_FULL_INDEX_ENABLED,
    SKILL_CATALOG_FULL_INDEX_LIMIT,
    SKILL_CONTRACT_FORBIDDEN_PATHS,
    SKILL_CONTRACT_FORBIDDEN_PATTERNS,
    SKILL_DISCLOSURE_DEFAULT,
    SKILL_DISCLOSURE_VALID,
    SKILL_OFFENSIVE_AUTHORIZED_NATURES,
    SKILL_OFFENSIVE_ENABLED,
    SKILL_POSTURE_DEFAULT,
    SKILL_POSTURE_VALID,
    SKILL_STRATEGY_CAPABILITY_VIEW,
    SKILL_WRITE_MIN_RING,
    SKILL_WRITE_ROLES,
)

logger = logging.getLogger(__name__)

# Directory marker for built-in (read-only) skills shipped with the repo.
_BUILTIN_SKILL_DIR = "config/skills"


def _is_builtin_path(path: str) -> bool:
    """Return True when a skill file lives under the built-in skills dir."""
    return _BUILTIN_SKILL_DIR in path.replace("\\", "/")


def validate_skill_content(prompt: str, description: str = "") -> list[str]:
    """Validate evolved-skill content against the built-in catalog contract.

    Checks a skill's prompt+description for:
      1. Constitutional-violation instructions (bypass sandbox, modify
         constitution, write outside territory, skip gates, swallow
         exceptions) — mirror of ``test_skill_contracts`` patterns.
      2. Project-specific path/identifier literals that would prevent the
         skill from generalizing to other projects.

    Returns the list of violations (empty = clean). The caller decides
    whether to scrub or reject; this function never mutates anything.
    """
    import re as _re

    violations: list[str] = []
    text = f"{prompt or ''}\n{description or ''}"
    for pat in SKILL_CONTRACT_FORBIDDEN_PATTERNS:
        if _re.search(pat, text, _re.IGNORECASE):
            violations.append(f"constitutional pattern: {pat}")
    for lit in SKILL_CONTRACT_FORBIDDEN_PATHS:
        if lit in text:
            violations.append(f"project-specific literal: {lit}")
    return violations


def _get_skill_dirs() -> list[str]:
    """Get skill discovery dirs from config, fall back to built-in paths."""
    try:
        from l1.kernel.discovery import get_config

        cfg = get_config("skill_dirs")
        if cfg and isinstance(cfg, list):
            return cfg
    except Exception:
        logger.debug("skill: skill_dirs config lookup failed, using defaults", exc_info=True)
    return [".praxis/skills", "skills", ".skills"]


SKILL_DIRS = _get_skill_dirs()


def resolve_skill_dirs() -> list[str]:
    """Return skill discovery paths via PraxisPaths (deploy-mode aware)."""
    try:
        from .paths import get_paths

        return get_paths().skill_dirs
    except Exception:
        return list(SKILL_DIRS)


def _derive_role(agent_id: str) -> str:
    """Derive a role name from an agent id (``agent-writer`` → ``writer``)."""
    if agent_id in ("l3", "human"):
        return agent_id
    for prefix in ("agent-", "agent_"):
        if agent_id.startswith(prefix):
            return agent_id[len(prefix) :]
    return agent_id


_UNIVERSAL_PRINCIPLES_RE = re.compile(r"^## Universal Principles.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def _strip_universal_principles(body: str) -> str:
    """Remove the duplicated universal-principles section from a skill body.

    The 12 governance principles are normalized into
    ``config/skills/_shared/principles.md`` and injected once per skill at
    load; the per-file section is stripped so sources stay slim and edits
    do not drift across 21 files.
    """
    return _UNIVERSAL_PRINCIPLES_RE.sub("", body, count=1)


@dataclass
class Skill:
    """Skill — skill record (name, description, rules, procedures, knowledge)."""

    name: str
    description: str = ""
    rules: list[str] = field(default_factory=list)
    procedures: list[dict] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    loaded_at: float = 0.0
    allowed_tools: list[str] | None = None
    variables: list[str] | None = None
    prompt: str = ""
    posture: str = SKILL_POSTURE_DEFAULT

    def expand(self, **kwargs: str) -> str:
        """Expand $VARIABLES in prompt with keyword args."""
        if not self.prompt:
            return self.prompt
        result = self.prompt
        for k, v in kwargs.items():
            result = result.replace(f"${k.upper()}", str(v))
        return result

    def to_dict(self) -> dict:
        """Serialize the skill to a plain dict for inspection and persistence."""
        return {
            "name": self.name,
            "description": self.description,
            "rules": len(self.rules),
            "procedures": len(self.procedures),
            "knowledge": self.knowledge,
            "source": self.source,
            "allowed_tools": self.allowed_tools or [],
            "variables": self.variables or [],
            "prompt": self.prompt or "",
            "tags": [],
            "posture": self.posture,
            "loaded_at": self.loaded_at,
        }


class SkillManager:
    """Manages agent skills — load, list, query at runtime."""

    def __init__(self):
        self._skills: dict[str, dict] = {}
        # RLock: delete() calls _drop_skill_from_cells() while holding the lock
        # (reentrant — see AGENTS.md threading convention).
        self._lock = threading.RLock()
        # Per-Cell skill white-list: cell_id → set of skill names.
        # Cells bind the skills they are allowed to inject; unbound cells
        # fall back to the global pool (backward compatible).
        self._cell_skill_map: dict[str, set[str]] = {}
        # Write-gate policy — compile-time defaults; L3 config center may
        # inject overrides via set_write_policy() (kernel never imports L3).
        self._write_min_ring: int = SKILL_WRITE_MIN_RING
        self._write_roles: tuple[str, ...] = SKILL_WRITE_ROLES
        # Offensive-posture gate policy — compile-time defaults; L3 config
        # center and the API may inject overrides via set_offensive_policy()
        # at runtime (soft control, see SKILL_OFFENSIVE_ENABLED).
        self._offensive_enabled: bool = SKILL_OFFENSIVE_ENABLED
        self._offensive_natures: tuple[str, ...] = SKILL_OFFENSIVE_AUTHORIZED_NATURES
        # Distillation/DPO master switches — compile-time defaults; the API
        # and config center may override at runtime (see
        # /api/v2/skills/distill-policy). R4Agent gates its pipeline on these.
        # ``_distill_sub`` holds the per-stage sub-switches (generalize /
        # llm_distill / clustering / sampling) so the pipeline can degrade
        # one notch at a time instead of all-or-nothing.
        self._distill_enabled: bool = R4_DISTILL_ENABLED
        self._dpo_signal_enabled: bool = R4_DPO_SIGNAL_ENABLED
        self._distill_sub: dict[str, bool] = {
            "generalize": R4_DISTILL_SUB_GENERALIZE,
            "llm_distill": R4_DISTILL_SUB_LLM,
            "clustering": R4_DISTILL_SUB_CLUSTERING,
            "sampling": R4_DISTILL_SUB_SAMPLING,
        }
        self._distill_updated: float = 0.0
        self._distill_source: str = "params"
        # Retrieval/curation pipeline policy — runtime knobs for the R4
        # pipeline stages (task-similarity ranking, contribution curation and
        # their scoring thresholds). Overridable via set_pipeline_policy();
        # params provide the compile-time defaults.
        self._retrieval_enabled: bool = R4_RETRIEVAL_ENABLED
        self._curation_enabled: bool = R4_CURATION_ENABLED
        self._contrib_min_trials: int = R4_CONTRIB_MIN_TRIALS
        self._contrib_min_ratio: float = R4_CONTRIB_MIN_RATIO
        self._retrieval_min_score: float = R4_RETRIEVAL_MIN_SCORE
        self._pipeline_updated: float = 0.0
        self._pipeline_source: str = "params"
        # Progressive-disclosure policy — runtime knobs for the session
        # catalog (two-level index, audience filter, L3A capability view).
        self._full_index_enabled: bool = SKILL_CATALOG_FULL_INDEX_ENABLED
        self._full_index_limit: int = SKILL_CATALOG_FULL_INDEX_LIMIT
        self._audience_filter_enabled: bool = SKILL_AUDIENCE_FILTER_ENABLED
        self._strategy_capability_view: bool = SKILL_STRATEGY_CAPABILITY_VIEW
        self._disclosure_updated: float = 0.0
        self._disclosure_source: str = "params"
        # Quest-style staged skills: (skill, session_key) → active stage index.
        self._stage_state: dict[tuple[str, str], int] = {}
        # Universal principles normalized into a single shared layer
        # (config/skills/_shared/principles.md) — injected at load time.
        self._shared_principles: str = ""
        # Structural-mutation revision — R4Agent injection caches compare this
        # to decide whether their derived skill lists are stale.
        self._revision = 0

    def set_distill_policy(
        self,
        distill: bool | None = None,
        dpo_signal: bool | None = None,
        sub: dict | None = None,
        source: str = "runtime",
    ) -> dict:
        """Override the distillation/DPO switches at runtime (API/config).

        ``distill=False`` disables the whole pipeline (master);
        ``dpo_signal=False`` disables card→skill preference weighting;
        ``sub`` optionally sets individual stage switches, e.g.
        ``{"clustering": False}`` degrades clustering only (falls back to
        by-tool grouping). ``source`` records who last changed the policy
        (params/config/runtime/API) for auditability. None fields are left
        untouched, so a caller can flip just one knob.
        """
        with self._lock:
            if distill is not None:
                self._distill_enabled = bool(distill)
            if dpo_signal is not None:
                self._dpo_signal_enabled = bool(dpo_signal)
            if sub and isinstance(sub, dict):
                for k, v in sub.items():
                    if k in self._distill_sub:
                        self._distill_sub[k] = bool(v)
            if distill is not None or dpo_signal is not None or sub:
                self._distill_updated = time.time()
                self._distill_source = source
            return {
                "success": True,
                "distill": self._distill_enabled,
                "dpo_signal": self._dpo_signal_enabled,
                "sub": dict(self._distill_sub),
                "updated": self._distill_updated,
                "source": self._distill_source,
            }

    def distill_policy(self) -> dict:
        """Return the current distillation/DPO policy (master + sub-switches)."""
        with self._lock:
            return {
                "distill": self._distill_enabled,
                "dpo_signal": self._dpo_signal_enabled,
                "sub": dict(self._distill_sub),
                "updated": self._distill_updated,
                "source": self._distill_source,
            }

    def set_pipeline_policy(
        self,
        retrieval: bool | None = None,
        curation: bool | None = None,
        contrib_min_trials: int | None = None,
        contrib_min_ratio: float | None = None,
        retrieval_min_score: float | None = None,
        source: str = "runtime",
    ) -> dict:
        """Override the retrieval/curation pipeline knobs at runtime (API/config).

        ``retrieval=False`` disables task-similarity ranking (falls back to
        deterministic ordering); ``curation=False`` disables contribution-based
        retirement/eviction; the threshold fields tune scoring granularity.
        None fields are left untouched. ``source`` records who changed the
        policy for auditability.
        """
        with self._lock:
            if retrieval is not None:
                self._retrieval_enabled = bool(retrieval)
            if curation is not None:
                self._curation_enabled = bool(curation)
            if contrib_min_trials is not None:
                self._contrib_min_trials = int(contrib_min_trials)
            if contrib_min_ratio is not None:
                self._contrib_min_ratio = float(contrib_min_ratio)
            if retrieval_min_score is not None:
                self._retrieval_min_score = float(retrieval_min_score)
            self._pipeline_updated = time.time()
            self._pipeline_source = source
            return {
                "success": True,
                "retrieval": self._retrieval_enabled,
                "curation": self._curation_enabled,
                "contrib_min_trials": self._contrib_min_trials,
                "contrib_min_ratio": self._contrib_min_ratio,
                "retrieval_min_score": self._retrieval_min_score,
                "updated": self._pipeline_updated,
                "source": self._pipeline_source,
            }

    def pipeline_policy(self) -> dict:
        """Return the current retrieval/curation pipeline policy."""
        with self._lock:
            return {
                "retrieval": self._retrieval_enabled,
                "curation": self._curation_enabled,
                "contrib_min_trials": self._contrib_min_trials,
                "contrib_min_ratio": self._contrib_min_ratio,
                "retrieval_min_score": self._retrieval_min_score,
                "updated": self._pipeline_updated,
                "source": self._pipeline_source,
            }

    def set_disclosure_policy(
        self,
        full_index_enabled: bool | None = None,
        full_index_limit: int | None = None,
        audience_filter_enabled: bool | None = None,
        strategy_capability_view: bool | None = None,
        source: str = "runtime",
    ) -> dict:
        """Override the progressive-disclosure knobs at runtime (API/config).

        ``full_index_enabled`` appends the full skill index after the curated
        catalog slots; ``audience_filter_enabled`` toggles strategy/execution
        audience routing; ``strategy_capability_view`` gives the L3A decision
        layer a read-only view of execution capabilities. None fields are
        left untouched; ``source`` records who changed the policy.
        """
        with self._lock:
            if full_index_enabled is not None:
                self._full_index_enabled = bool(full_index_enabled)
            if full_index_limit is not None:
                self._full_index_limit = int(full_index_limit)
            if audience_filter_enabled is not None:
                self._audience_filter_enabled = bool(audience_filter_enabled)
            if strategy_capability_view is not None:
                self._strategy_capability_view = bool(strategy_capability_view)
            self._disclosure_updated = time.time()
            self._disclosure_source = source
            return {
                "success": True,
                "full_index_enabled": self._full_index_enabled,
                "full_index_limit": self._full_index_limit,
                "audience_filter_enabled": self._audience_filter_enabled,
                "strategy_capability_view": self._strategy_capability_view,
                "updated": self._disclosure_updated,
                "source": self._disclosure_source,
            }

    def disclosure_policy(self) -> dict:
        """Return the current progressive-disclosure policy."""
        with self._lock:
            return {
                "full_index_enabled": self._full_index_enabled,
                "full_index_limit": self._full_index_limit,
                "audience_filter_enabled": self._audience_filter_enabled,
                "strategy_capability_view": self._strategy_capability_view,
                "updated": self._disclosure_updated,
                "source": self._disclosure_source,
            }

    # ── Quest-style staged skills (per-session stage state) ──

    def current_stage(self, name: str, session_key: str = "") -> dict:
        """Return the active stage of a staged skill for a session.

        Unstaged skills return ``staged: False``. The stage index is
        per-session (session_key, typically the agent/card id) so parallel
        sessions never interfere.
        """
        skill = self._skills.get(name)
        stages = skill.get("stages") if skill else None
        if not stages:
            return {"skill": name, "staged": False, "stage": None}
        with self._lock:
            idx = self._stage_state.get((name, session_key), 0)
            # Register only card-scoped sessions: on_card_complete consumes
            # "card:" keys exclusively, so registering bare agent ids here
            # would grow _stage_state forever without ever being advanced
            # (unbounded singleton growth + dead entries).
            if session_key.startswith("card:"):
                self._stage_state.setdefault((name, session_key), 0)
        idx = max(0, min(idx, len(stages) - 1))
        stage = stages[idx]
        return {
            "skill": name,
            "staged": True,
            "stage_index": idx,
            "stage": stage,
            "next_stage": stages[idx + 1].get("id") if idx + 1 < len(stages) else None,
            "done": idx >= len(stages) - 1,
        }

    def advance_stage(self, name: str, session_key: str = "") -> dict:
        """Advance a staged skill to its next stage for a session."""
        skill = self._skills.get(name)
        stages = skill.get("stages") if skill else None
        if not stages:
            return {"success": True, "skill": name, "staged": False}
        with self._lock:
            idx = self._stage_state.get((name, session_key), 0)
            if idx < len(stages) - 1:
                idx += 1
                self._stage_state[(name, session_key)] = idx
            return {
                "success": True,
                "skill": name,
                "stage_index": idx,
                "done": idx >= len(stages) - 1,
            }

    # ── Guided-path engine (quest-style skill chain) ──

    def _guidance_graph(self) -> dict[str, set[str]]:
        """Build the skill guidance DAG: skill → set of skills it unlocks.

        Edges come from both directions: a skill's ``dependencies`` (prereq
        skills that must be satisfied) and ``next`` (forward guidance). The
        graph is rebuilt lazily per call — the registry is small.
        """
        graph: dict[str, set[str]] = {}
        with self._lock:
            for name, skill in self._skills.items():
                deps = [d for d in (skill.get("dependencies") or []) if isinstance(d, str)]
                for d in deps:
                    graph.setdefault(d, set()).add(name)
                nxt = [n for n in (skill.get("next") or []) if isinstance(n, str)]
                for n in nxt:
                    graph.setdefault(name, set()).add(n)
        return graph

    def validate_guidance_graph(self) -> dict:
        """Detect cycles in the skill guidance DAG (fail-fast on edits)."""
        graph = self._guidance_graph()
        white, gray, black = 0, 1, 2
        color: dict[str, int] = {}
        stack: list[str] = []
        cycles: list[list[str]] = []

        def dfs(node: str) -> None:
            color[node] = gray
            stack.append(node)
            for nxt in graph.get(node, ()):
                if color.get(nxt, white) == white:
                    dfs(nxt)
                elif color.get(nxt) == gray:
                    idx = stack.index(nxt) if nxt in stack else 0
                    cycles.append(stack[idx:] + [nxt])
            stack.pop()
            color[node] = black

        for node in graph:
            if color.get(node, white) == white:
                dfs(node)
        return {"acyclic": not cycles, "cycles": cycles, "nodes": len(graph)}

    def guided_frontier(self, completed: list[str] | None = None) -> list[str]:
        """Return the currently unlocked skills (quest-log frontier).

        ``completed`` = skill names whose prerequisites are satisfied. Skills
        with unsatisfied (missing or incomplete) dependencies are excluded.
        """
        completed_set = set(completed or [])
        frontier: list[str] = []
        with self._lock:
            for name, skill in self._skills.items():
                if skill.get("disclosure", "full") == "none":
                    continue
                deps = [d for d in (skill.get("dependencies") or []) if isinstance(d, str)]
                if all(d in completed_set for d in deps):
                    frontier.append(name)
        frontier.sort()
        return frontier

    def guided_path(self, target: str) -> list[str]:
        """Reverse-chain the prerequisite path to *target* (BFS over deps)."""
        with self._lock:
            deps_of = {
                name: [d for d in (skill.get("dependencies") or []) if isinstance(d, str)]
                for name, skill in self._skills.items()
            }
        chain: list[str] = []
        seen: set[str] = set()
        queue: list[str] = [target]
        while queue:
            node = queue.pop(0)
            if node in seen or node not in self._skills:
                continue
            seen.add(node)
            chain.append(node)
            queue.extend(deps_of.get(node, []))
        chain.reverse()
        return chain

    def on_card_complete(self, card_id: str, state: str = "", result: dict | None = None) -> dict:
        """Advance staged skills bound to a card session (three-table linkage).

        Called by the card completion listener (see l3.memory.skill_guidance);
        advances the stage state of every staged skill used under this card's
        session key. Returns the number of stages advanced.
        """
        if state and state.upper() not in ("COMPLETED", "DONE"):
            return {"advanced": 0}
        session_key = f"card:{card_id}"
        advanced = 0
        with self._lock:
            for (name, key), idx in list(self._stage_state.items()):
                if key != session_key:
                    continue
                skill = self._skills.get(name)
                stages = skill.get("stages") if skill else None
                if stages and idx < len(stages) - 1:
                    self._stage_state[(name, key)] = idx + 1
                    advanced += 1
        return {"advanced": advanced, "session_key": session_key}

    # ── Per-Cell skill binding (回灌到 Cell) ──

    def bind_skill(self, cell_id: str, name: str) -> dict:
        """Bind a skill to a Cell so it is injected only for that Cell.

        Args:
            cell_id: Cell identifier.
            name: Skill name to allow for the Cell.
        """
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            self._cell_skill_map.setdefault(cell_id, set()).add(name)
            self._revision += 1
            return {"success": True, "cell_id": cell_id, "skill": name}

    def unbind_skill(self, cell_id: str, name: str) -> dict:
        """Remove a skill binding from a Cell."""
        with self._lock:
            cell_set = self._cell_skill_map.get(cell_id)
            if not cell_set or name not in cell_set:
                return {"success": False, "error": f"skill '{name}' not bound to '{cell_id}'"}
            cell_set.discard(name)
            self._revision += 1
            return {"success": True, "cell_id": cell_id, "skill": name}

    def skills_for_cell(self, cell_id: str) -> set[str]:
        """Return the set of skill names bound to a Cell (empty = global pool)."""
        with self._lock:
            return set(self._cell_skill_map.get(cell_id, set()))

    def cells_for_skill(self, name: str) -> list[str]:
        """Return all Cell ids that have bound this skill."""
        with self._lock:
            return [cid for cid, s in self._cell_skill_map.items() if name in s]

    def _drop_skill_from_cells(self, name: str) -> None:
        """Remove a deleted skill from every Cell binding."""
        with self._lock:
            for cell_set in self._cell_skill_map.values():
                cell_set.discard(name)

    def set_write_policy(self, min_ring: int | None = None, roles: list[str] | tuple[str, ...] | None = None) -> dict:
        """Override the write-gate policy (called by L3 config center / API).

        Args:
            min_ring: Minimum ring clearance to mutate skills.
            roles: Additional roles allowed to mutate skills.
        """
        with self._lock:
            if min_ring is not None:
                self._write_min_ring = int(min_ring)
            if roles is not None:
                self._write_roles = tuple(roles)
        return {
            "success": True,
            "write_min_ring": self._write_min_ring,
            "write_roles": list(self._write_roles),
        }

    def write_policy(self) -> dict:
        """Return the current write-gate policy (for API/CLI exposure)."""
        with self._lock:
            return {
                "write_min_ring": self._write_min_ring,
                "write_roles": list(self._write_roles),
            }

    def set_offensive_policy(
        self,
        enabled: bool | None = None,
        natures: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        """Override the offensive-posture gate policy at runtime (API/config).

        Soft control ("honest-agent" gate): ``enabled=False`` bypasses the
        posture gate entirely; ``natures`` replaces the card natures that
        authorize offensive-skill injection. Neither field is required, so a
        caller can flip just one. Applied atomically under the manager lock.
        """
        with self._lock:
            if enabled is not None:
                self._offensive_enabled = bool(enabled)
            if natures is not None:
                self._offensive_natures = tuple(n for n in natures if isinstance(n, str))
            return {
                "success": True,
                "enabled": self._offensive_enabled,
                "natures": list(self._offensive_natures),
            }

    def offensive_policy(self) -> dict:
        """Return the current offensive-posture gate policy (for API/CLI)."""
        with self._lock:
            return {
                "enabled": self._offensive_enabled,
                "natures": list(self._offensive_natures),
            }

    def offensive_authorized(self, nature: str) -> bool:
        """Whether an offensive-posture skill may be used for a card nature.

        Gate disabled → authorized for any nature (soft-control bypass).
        Gate enabled → authorized only for natures in the policy allow-list
        (default: SKILL_OFFENSIVE_AUTHORIZED_NATURES). Consulted by AgentLoop
        injection, SkillCatalogHook and use_skill.
        """
        with self._lock:
            if not self._offensive_enabled:
                return True
            return nature in self._offensive_natures

    def load_dir(self, directory: str) -> int:
        """Load all skill files from a directory tree.

        Supports:
          - SKILL.md files (Markdown with frontmatter)
          - .yaml/.yml skill definitions
        """
        import yaml

        count = 0
        base = os.path.abspath(directory)
        if not os.path.isdir(base):
            return 0
        # Universal principles live once in <base>/_shared/principles.md and
        # are injected into every loaded skill (normalization: no per-file
        # duplication of the 12 governance principles).
        shared_path = os.path.join(base, "_shared", "principles.md")
        if os.path.isfile(shared_path):
            with open(shared_path, encoding="utf-8") as f:
                self._shared_principles = f.read().strip()
        for root, _dirs, files in os.walk(base):
            for fn in files:
                fp = os.path.join(root, fn)
                if fn == "SKILL.md":
                    if self._load_markdown(fp):
                        count += 1
                elif fn.endswith((".yaml", ".yml")):
                    try:
                        with open(fp, encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                        if isinstance(data, dict) and "name" in data:
                            self._store(data, fp)
                            count += 1
                    except Exception as e:
                        logger.warning("kernel/skill: %s", e)
        if count > 0:
            self._revision += 1
        return count

    def load_builtin(self) -> int:
        """Load built-in skills from deploy-mode-aware search paths."""
        count = 0
        dirs = resolve_skill_dirs()
        import l1.kernel as _kernel

        kernel_dir = os.path.dirname(_kernel.__file__)
        for sd in dirs:
            if os.path.isabs(sd):
                # Absolute path — use directly
                count += self.load_dir(sd)
            else:
                # Relative path — try project root, then src/
                # kernel_dir = <root>/src/l1/kernel → project root is 3 levels up.
                for base in [
                    os.path.join(kernel_dir, "..", "..", ".."),  # project root
                    os.path.join(kernel_dir, "..", ".."),  # src/
                ]:
                    path = os.path.join(base, sd)
                    if os.path.isdir(path):
                        count += self.load_dir(path)
                        break
        # Also load evolved skills from data directory
        try:
            from ..paths import get_paths as _gp

            if os.path.isdir(_gp().skill_evolved_dir):
                count += self.load_dir(_gp().skill_evolved_dir)
        except Exception:
            logger.debug("skill: evolved skills load failed")
        return count

    def authorize_write(self, agent_id: str = "", role: str = "", internal: bool = False) -> tuple[bool, str]:
        """Check whether a caller may create/update/delete skills.

        Developer-only policy: only roles with ring clearance >=
        ``skill.write_min_ring`` (SettingsCenter-configurable, default
        ``SKILL_WRITE_MIN_RING``) or in ``skill.write_roles`` (default
        ``SKILL_WRITE_ROLES``) may mutate skills; ordinary users are
        read-only.  A caller with neither ``agent_id`` nor ``role`` is
        treated as a system-internal caller and allowed **only** when
        ``internal=True`` (boot-time loading, R4Agent evolution/pruning).
        External entry points (shell/API) must pass an explicit identity
        and may not claim ``system`` by omission.
        """
        if not agent_id and not role:
            return (True, "system") if internal else (False, "identity required: provide agent_id or role")
        with self._lock:
            min_ring = self._write_min_ring
            write_roles = self._write_roles
        resolved = role or _derive_role(agent_id)
        ring = AGENT_CLEARANCE.get(resolved, 0)
        if resolved in write_roles or ring >= min_ring:
            return True, resolved
        return False, (
            f"role '{resolved}' (ring {ring}) lacks skill write clearance "
            f"(need ring>={min_ring} or role in {list(write_roles)})"
        )

    def register(self, name: str, data: dict, agent_id: str = "", role: str = "", internal: bool = False) -> dict:
        """Register a skill programmatically (developer-only).

        ``internal=True`` allows identity-less writes from system processes
        (boot loading, R4Agent); external callers must pass an identity.
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        with self._lock:
            existing = self._skills.get(name)
        if existing and existing.get("builtin"):
            return {"success": False, "error": f"permission denied: builtin skill '{name}' is read-only"}
        with self._lock:
            self._skills[name] = data
            self._revision += 1
            self._emit_mutated("register", name, agent_id, who)
            return {"success": True, "skill": name, "authorized": who}

    def create(
        self,
        name: str,
        description: str = "",
        prompt: str = "",
        tags: list[str] | None = None,
        rules: list[str] | None = None,
        procedures: list[dict] | None = None,
        allowed_tools: list[str] | None = None,
        dependencies: list[str] | None = None,
        dependency_kind: str = "soft",
        posture: str = SKILL_POSTURE_DEFAULT,
        disclosure: str = SKILL_DISCLOSURE_DEFAULT,
        stages: list[dict] | None = None,
        next_skills: list[str] | None = None,
        knowledge: dict | None = None,
        agent_id: str = "",
        role: str = "",
        internal: bool = False,
    ) -> dict:
        """Create a skill programmatically with structured fields (developer-only).

        ``internal=True`` allows identity-less writes from system processes
        (boot loading, R4Agent); external callers must pass an identity.
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        data = {
            "name": name,
            "description": description[:LOG_TRUNC_200],
            "prompt": prompt,
            "rules": rules or [],
            "procedures": procedures or [],
            "knowledge": knowledge if knowledge is not None else {"evolved": True, "prompt": prompt[:LOG_TRUNC_2000]},
            "tags": tags or [],
            "allowed_tools": allowed_tools,
            "dependencies": dependencies or [],
            "dependency_kind": dependency_kind if dependency_kind in ("hard", "soft") else "soft",
            "posture": self._normalize_posture(posture),
            "disclosure": self._normalize_disclosure(disclosure),
            "stages": [s for s in (stages or []) if isinstance(s, dict)],
            "next": [n for n in (next_skills or []) if isinstance(n, str)],
            "source": "evolved",
            "loaded_at": __import__("time").time(),
            "useful_count": 0,
        }
        return self.register(name, data, agent_id=agent_id, role=role, internal=internal)

    def get(self, name: str) -> dict | None:
        """Return the skill record for *name*, or None."""
        with self._lock:
            return self._skills.get(name)

    def structured_skill(self, name: str, session_key: str = "") -> dict:
        """Return a skill as pure structure — the agent-facing view.

        The human-readable SKILL.md stays the source of truth; this
        projection (rules/procedures/stages as machine-readable items plus
        the current stage) is what the agent consumes at runtime — the raw
        markdown body is excluded (full content stays on the human/review
        layer).
        """
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "error": f"skill '{name}' not found"}
        stage = None
        if skill.get("stages"):
            stage = self.current_stage(name, session_key)
        return {
            "success": True,
            "name": name,
            "description": skill.get("description", ""),
            "rules": list(skill.get("rules") or []),
            "procedures": list(skill.get("procedures") or []),
            "allowed_tools": skill.get("allowed_tools") or [],
            "variables": skill.get("variables") or [],
            "dependencies": skill.get("dependencies") or [],
            "next": skill.get("next") or [],
            "disclosure": skill.get("disclosure", SKILL_DISCLOSURE_DEFAULT),
            "stage": stage,
        }

    def list_skills(
        self, tags: list[str] | None = None, limit: int = 0, sort_by: str = "name", include_prompt: bool = False
    ) -> list[dict]:
        """List skills, optionally filtered by tags and sorted.

        Args:
            tags: Filter by these tags (any match).
            limit: Max results (0 = unlimited).
            sort_by: Sort key: ``"name"`` (default), ``"loaded_at"``, ``"last_used"``.
        """
        with self._lock:
            items = list(self._skills.items())
        result = []
        for n, s in items:
            if tags:
                skill_tags = s.get("tags", [])
                if not any(t in skill_tags for t in tags):
                    continue
            result.append(
                {
                    "name": n,
                    "description": s.get("description", "")[:LOG_TRUNC_60],
                    "rules": len(s.get("rules", [])),
                    "procedures": len(s.get("procedures", [])),
                    "tags": s.get("tags", []),
                    "prompt": s.get("prompt", "") if include_prompt else "",
                    "source": s.get("source", ""),
                    "builtin": bool(s.get("builtin")),
                    "posture": s.get("posture", SKILL_POSTURE_DEFAULT),
                    "disclosure": s.get("disclosure", SKILL_DISCLOSURE_DEFAULT),
                    "stages": len(s.get("stages") or []),
                    "next": s.get("next") or [],
                    "loaded_at": s.get("loaded_at", 0.0),
                    "last_used": s.get("last_used", 0.0),
                    "disable_model_invocation": bool(s.get("disable_model_invocation")),
                    "dependencies": s.get("dependencies", []),
                    "dependency_kind": s.get("dependency_kind", "soft"),
                }
            )
        if sort_by == "loaded_at":
            result.sort(key=lambda x: -x["loaded_at"])
        elif sort_by == "last_used":
            result.sort(key=lambda x: -x["last_used"])
        else:
            result.sort(key=lambda x: x["name"])
        if limit > 0:
            result = result[:limit]
        return result

    def rules_for(self, domain: str = "") -> list[str]:
        """Get all rules matching a domain (e.g., 'python', 'go', 'review')."""
        domain_lower = domain.lower()
        rules = []
        with self._lock:
            for name, skill in self._skills.items():
                if domain_lower and domain_lower not in name.lower():
                    continue
                rules.extend(skill.get("rules", []))
        return rules

    def list_by_allowed_tools(self, tool_name: str) -> list[dict]:
        """List skills that allow using a specific tool."""
        results = []
        with self._lock:
            for name, skill in self._skills.items():
                at = skill.get("allowed_tools")
                if at is None or tool_name in at:
                    results.append(
                        {
                            "name": name,
                            "description": skill.get("description", "")[:LOG_TRUNC_60],
                        }
                    )
        return results

    def update(self, name: str, data: dict, agent_id: str = "", role: str = "", internal: bool = False) -> dict:
        """Update a skill's data at runtime (developer-only).

        Ordinary callers may only bump usage metadata (``last_used``);
        structural edits require write clearance.  ``internal=True`` allows
        identity-less structural writes from system processes.
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            builtin = bool(self._skills[name].get("builtin"))
            # Usage bookkeeping is harmless for any caller.
            if set(data.keys()) <= {"last_used", "usage_count", "useful_count"}:
                self._skills[name].update(data)
                return {"success": True, "skill": name}
            if builtin:
                return {"success": False, "error": f"permission denied: builtin skill '{name}' is read-only"}
            if not ok:
                return {"success": False, "error": f"permission denied: {who}"}
            self._skills[name].update(data)
            self._revision += 1
            self._emit_mutated("update", name, agent_id, who)
            return {"success": True, "skill": name, "authorized": who}

    def bump_usage(self, name: str, key: str = "useful_count") -> dict:
        """Atomically increment a usage counter on a skill.

        Performs the read-modify-write under a single lock acquisition so
        concurrent callers (e.g. parallel ``use_skill`` invocations) never
        lose an increment.  Usage bookkeeping requires no write clearance.
        """
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            current = self._skills[name].get(key, 0) or 0
            self._skills[name][key] = current + 1
            self._skills[name]["last_used"] = time.time()
            return {"success": True, "skill": name, key: current + 1}

    def revision(self) -> int:
        """Return the structural-mutation revision (R4Agent cache invalidation)."""
        with self._lock:
            return self._revision

    def delete(self, name: str, agent_id: str = "", role: str = "", internal: bool = False) -> dict:
        """Delete a skill from the runtime registry (developer-only).

        ``internal=True`` allows identity-less deletes from system processes
        (R4Agent TTL pruning); external callers must pass an identity.
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            if self._skills[name].get("builtin"):
                return {"success": False, "error": f"permission denied: builtin skill '{name}' is read-only"}
            del self._skills[name]
            self._revision += 1
            self._drop_skill_from_cells(name)
            self._emit_mutated("delete", name, agent_id, who)
            return {"success": True, "skill": name, "authorized": who}

    @staticmethod
    def _emit_mutated(action: str, name: str, agent_id: str, who: str) -> None:
        """Emit an EVENT_SKILL_MUTATED audit signal (best-effort, lazy import)."""
        try:
            from l1.kernel.event import get_bus
            from l1.kernel.params.agent import EVENT_SKILL_MUTATED

            # String-typed emit registers the custom signal type on first use
            # (emit_signal would KeyError on the unregistered type lookup).
            get_bus().emit_event(EVENT_SKILL_MUTATED, data={"action": action, "skill": name}, source=agent_id or who)
        except Exception:
            # Audit is best-effort — never break the mutation on signal failure.
            logger.debug("skill: mutation audit signal failed (best-effort)", exc_info=True)

    def query(self, question: str) -> list[dict]:
        """Query skills by keyword matching.

        Uses TF-IDF-like scoring: term frequency in name (weight 3),
        description (weight 2), rules (weight 1), and prompt (weight 0.5).
        """
        import re as _re

        q = question.lower().strip()
        if not q:
            return []
        terms = set(_re.split(r"[\s,;:._-]+", q))
        results: list[dict[str, Any]] = []
        with self._lock:
            for name, skill in self._skills.items():
                score = 0.0
                name_lower = name.lower()
                desc = skill.get("description", "").lower()
                prompt = (skill.get("prompt", "") or "")[:LOG_TRUNC_2000].lower()
                rules = [r.lower() for r in skill.get("rules", [])]
                for t in terms:
                    if not t:
                        continue
                    # Name hits (weight 3)
                    count = name_lower.count(t)
                    if count:
                        score += 3.0 * count
                    # Description hits (weight 2)
                    count = desc.count(t)
                    if count:
                        score += 2.0 * count
                    # Rules hits (weight 1)
                    for r in rules:
                        count = r.count(t)
                        if count:
                            score += 1.0 * count
                    # Prompt hits (weight 0.5)
                    count = prompt.count(t)
                    if count:
                        score += 0.5 * count
                if score > 0:
                    results.append({"name": name, "score": round(score, 1), "skill": skill})
        results.sort(key=lambda x: float(x["score"]), reverse=True)
        return results

    def skill_vfs_content(self) -> str:
        """Generate /skills/ virtual filesystem content."""
        lines = []
        for name in sorted(self._skills.keys()):
            skill = self._skills[name]
            desc = skill.get("description", "")[:LOG_TRUNC_50]
            rc = len(skill.get("rules", []))
            lines.append(f"{name:30s} {desc:50s} [{rc} rules]")
        return "\n".join(lines) if lines else "(no skills loaded)"

    def _load_markdown(self, path: str) -> bool:
        """Parse SKILL.md file with YAML frontmatter."""
        import yaml

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return False
        # YAML frontmatter between --- ... ---
        import re

        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not m:
            return False
        try:
            meta = yaml.safe_load(m.group(1))
        except Exception:
            return False
        if not isinstance(meta, dict):
            return False
        body = _strip_universal_principles(content[m.end() :])
        if self._shared_principles:
            body = self._shared_principles + "\n\n" + body
        name = meta.get("name", os.path.basename(os.path.dirname(path)))
        desc = meta.get("description")
        data = {
            "name": name,
            "description": (desc or "")[:LOG_TRUNC_200],
            "rules": self._extract_rules(body),
            "procedures": self._extract_procedures(body),
            "knowledge": {"body": body[:LOG_TRUNC_2000]},
            "source": path,
            "builtin": _is_builtin_path(path),
            "allowed_tools": meta.get("allowed_tools"),
            "variables": meta.get("variables"),
            "tags": meta.get("tags") or [],
            "prompt": body.strip(),
            # Posture: productive (default) vs offensive (reverse/attack
            # testing). Invalid values fall back to the safe default so a
            # malformed frontmatter never escalates a skill's posture.
            "posture": self._normalize_posture(meta.get("posture")),
            "disclosure": self._normalize_disclosure(meta.get("disclosure")),
            # Quest-style staged skills: ordered stages, each with
            # id/name/instructions/completion — progressive disclosure reveals
            # only the active stage (see current_stage/advance_stage).
            "stages": [s for s in (meta.get("stages") or []) if isinstance(s, dict)],
            # Forward guidance (quest-style): skills this skill suggests next.
            "next": [n for n in (meta.get("next") or []) if isinstance(n, str)],
            # Matt-Pocock-style invocation model: user-invoked skills
            # (disable-model-invocation: true) are excluded from automatic
            # context injection; they only fire on explicit use.
            "disable_model_invocation": bool(meta.get("disable-model-invocation", False)),
            # Dependency metadata (ADR-0001 style): prerequisite skills plus
            # strength. hard = output is wrong without the dependency; soft =
            # output is just less sharp. Defaults keep legacy skills working.
            "dependencies": list(meta.get("dependencies") or []),
            "dependency_kind": str(meta.get("dependency-kind", "soft")),
            # Field defaults so reloaded skills match programmatic create()
            # (round-trip integrity — tags/useful_count/last_used must survive).
            "useful_count": 0,
            "last_used": 0.0,
            "loaded_at": time.time(),
        }
        # E1: constitutional gate at load time — a skill whose registration
        # violates the constitution (e.g. instructs bypassing sandbox/gates)
        # is rejected before it enters the pool (fail-fast).
        try:
            from l1.kernel.constitution import get_constitution

            cc = get_constitution().is_allowed("skill.load", "system", target=name)
            if not cc.get("allowed"):
                logger.warning("skill: load blocked by constitution: %s", cc.get("blocks"))
                return False
        except Exception as e:
            logger.debug("skill: constitution check skipped at load: %s", e)
        self._store(data, path)
        return True

    @staticmethod
    def _normalize_posture(value: Any) -> str:
        """Normalize a posture value to a valid posture, defaulting to productive.

        Invalid values (or missing) fall back to the safe default so a
        malformed frontmatter or caller can never escalate a skill's posture.
        """
        if isinstance(value, str) and value in SKILL_POSTURE_VALID:
            return value
        return SKILL_POSTURE_DEFAULT

    @staticmethod
    def _normalize_disclosure(value: Any) -> str:
        """Normalize a disclosure value to full|index|none, defaulting to full.

        Invalid values (or missing) fall back to the safe default so a
        malformed frontmatter never hides a skill by accident — full means
        the skill participates in all progressive-disclosure levels.
        """
        if isinstance(value, str) and value in SKILL_DISCLOSURE_VALID:
            return value
        return SKILL_DISCLOSURE_DEFAULT

    def _extract_rules(self, body: str) -> list[str]:
        """Extract DO/DON'T rules from markdown body.

        Accepts both ``- **DO:** ...`` and ``- DO: ...`` / ``- DO ...`` forms
        so rules written by ``evolve_skill`` (``- DO: rule``) round-trip.
        """
        rules = []
        import re

        for m in re.finditer(r"^[-*]\s+\*\*(DO|DON'T)\*\*:\s*(.+)$", body, re.MULTILINE):
            rules.append(f"{m.group(1)}: {m.group(2).strip()}")
        for m in re.finditer(r"^[-*]\s+(DO|DON'T)[\s:]+(.+)$", body, re.MULTILINE):
            rules.append(f"{m.group(1)}: {m.group(2).strip()}")
        return rules

    def _extract_procedures(self, body: str) -> list[dict]:
        """Extract structured procedure steps from the markdown body.

        Accepts ``- **1**: desc`` / ``- **step**: desc`` forms so both the
        builtin catalog and the LLM SkillArchitect contract
        (``{step, action, description}``) round-trip this shape.
        """
        procedures = []
        import re

        for m in re.finditer(r"^[-*]\s+\*\*([A-Za-z0-9_-]+)\*\*:\s*(.+)$", body, re.MULTILINE):
            procedures.append({"step": m.group(1), "description": m.group(2).strip()})
        return procedures

    def _store(self, data: dict, source: str = "") -> None:
        name = data.get("name", "unknown")
        data["source"] = source
        data["loaded_at"] = time.time()
        with self._lock:
            self._skills[name] = data


_manager: SkillManager | None = None
_manager_lock = threading.Lock()


# ── Audience routing (domain-based skill supply) ──
# Skills carry audience tags ("strategy" / "execution"); the audience of an
# agent is derived from its identity. Strategy skills serve the L3A central
# layer (policy flow); execution skills serve Cell peer agents (execution
# flow). Untagged skills are universal. This powers dynamic supply through
# use_skill (on-demand) instead of context injection.
_AUDIENCE_TAGS: Final[tuple[str, ...]] = ("strategy", "execution")
_AUDIENCE_STRATEGY_AGENTS: Final[frozenset[str]] = frozenset({"l3a"})


def audience_of(agent_id: str) -> str:
    """Audience domain for an agent: strategy (L3A) or execution (others)."""
    return "strategy" if agent_id in _AUDIENCE_STRATEGY_AGENTS else "execution"


def skill_visible(skill: dict, agent_id: str) -> bool:
    """Whether a skill is visible to an agent under audience routing.

    Untagged skills (system knowledge) are universal; a tagged skill is
    visible only to its own audience.
    """
    tags = set(skill.get("tags") or [])
    tagged = tags & set(_AUDIENCE_TAGS)
    if not tagged:
        return True
    return audience_of(agent_id) in tagged


def get_skill_manager() -> SkillManager:
    """Get the skill manager singleton (lazily created)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SkillManager()
    return _manager


def reset_skill_manager() -> None:
    """Reset the skill manager singleton to None (for tests / hot reset)."""
    global _manager
    _manager = None
