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
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Final

from l1.kernel.params.agent import AGENT_CLEARANCE
from l1.kernel.params.system import (
    LOG_TRUNC_50,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
    SKILL_WRITE_MIN_RING,
    SKILL_WRITE_ROLES,
)

logger = logging.getLogger(__name__)

# Directory marker for built-in (read-only) skills shipped with the repo.
_BUILTIN_SKILL_DIR = "config/skills"


def _is_builtin_path(path: str) -> bool:
    """Return True when a skill file lives under the built-in skills dir."""
    return _BUILTIN_SKILL_DIR in path.replace("\\", "/")


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
        # Structural-mutation revision — R4Agent injection caches compare this
        # to decide whether their derived skill lists are stale.
        self._revision = 0

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
            "knowledge": {"evolved": True, "prompt": prompt[:LOG_TRUNC_2000]},
            "tags": tags or [],
            "allowed_tools": allowed_tools,
            "dependencies": dependencies or [],
            "dependency_kind": dependency_kind if dependency_kind in ("hard", "soft") else "soft",
            "source": "evolved",
            "loaded_at": __import__("time").time(),
            "useful_count": 0,
        }
        return self.register(name, data, agent_id=agent_id, role=role, internal=internal)

    def get(self, name: str) -> dict | None:
        """Return the skill record for *name*, or None."""
        with self._lock:
            return self._skills.get(name)

    def list_skills(self, tags: list[str] | None = None, limit: int = 0, sort_by: str = "name") -> list[dict]:
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
                    "prompt": s.get("prompt", ""),
                    "source": s.get("source", ""),
                    "builtin": bool(s.get("builtin")),
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
        body = content[m.end() :]
        name = meta.get("name", os.path.basename(os.path.dirname(path)))
        desc = meta.get("description")
        data = {
            "name": name,
            "description": (desc or "")[:LOG_TRUNC_200],
            "rules": self._extract_rules(body),
            "procedures": [],
            "knowledge": {"body": body[:LOG_TRUNC_2000]},
            "source": path,
            "builtin": _is_builtin_path(path),
            "allowed_tools": meta.get("allowed_tools"),
            "variables": meta.get("variables"),
            "tags": meta.get("tags") or [],
            "prompt": body.strip(),
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
