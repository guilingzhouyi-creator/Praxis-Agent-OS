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
  sm.list()               # → all loaded skills
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


SKILL_DIRS = [
    ".opencode/skills",
    "skills",
    ".skills",
]


def resolve_skill_dirs() -> list[str]:
    """Return skill discovery paths via PraxisPaths (deploy-mode aware)."""
    try:
        from .paths import get_paths
        return get_paths().skill_dirs
    except Exception:
        return list(SKILL_DIRS)


@dataclass
class Skill:
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
        }


class SkillManager:
    """Manages agent skills — load, list, query at runtime."""

    def __init__(self):
        self._skills: dict[str, dict] = {}
        self._lock = threading.Lock()

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
        for root, dirs, files in os.walk(base):
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
                for base in [
                    os.path.join(os.path.dirname(kernel_dir), ".."),  # project root
                    os.path.dirname(kernel_dir),                      # src/
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
            # Also try PraxisPaths version
            try:
                ev = _gp().skill_evolved_dir
                if ev != _gp().skill_evolved_dir and os.path.isdir(ev):
                    count += self.load_dir(ev)
            except Exception:
                pass
        except Exception:
            pass
        return count

    def register(self, name: str, data: dict) -> dict:
        """Register a skill programmatically."""
        with self._lock:
            self._skills[name] = data
            return {"success": True, "skill": name}

    def create(self, name: str, description: str = "",
               prompt: str = "", tags: list[str] | None = None,
               rules: list[str] | None = None,
               procedures: list[dict] | None = None) -> dict:
        """Create a skill programmatically with structured fields."""
        data = {
            "name": name,
            "description": description[:200],
            "prompt": prompt,
            "rules": rules or [],
            "procedures": procedures or [],
            "knowledge": {"evolved": True, "prompt": prompt[:2000]},
            "tags": tags or [],
            "source": "evolved",
            "loaded_at": __import__("time").time(),
        }
        return self.register(name, data)

    def get(self, name: str) -> dict | None:
        with self._lock:
            return self._skills.get(name)

    def list(self, tags: list[str] | None = None,
             limit: int = 0) -> list[dict]:
        with self._lock:
            items = sorted(self._skills.items())
        result = []
        for n, s in items:
            if tags:
                skill_tags = s.get("tags", [])
                if not any(t in skill_tags for t in tags):
                    continue
            result.append({
                "name": n,
                "description": s.get("description", "")[:60],
                "rules": len(s.get("rules", [])),
                "procedures": len(s.get("procedures", [])),
                "tags": s.get("tags", []),
                "prompt": s.get("prompt", ""),
            })
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
                    results.append({
                        "name": name,
                        "description": skill.get("description", "")[:60],
                    })
        return results

    def update(self, name: str, data: dict) -> dict:
        """Update a skill's data at runtime (e.g., increment usage count)."""
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            self._skills[name].update(data)
            return {"success": True, "skill": name}

    def query(self, question: str) -> list[dict]:
        """Query skills by keyword matching."""
        q = question.lower()
        results = []
        with self._lock:
            for name, skill in self._skills.items():
                score = 0
                if q in name.lower():
                    score += 3
                desc = skill.get("description", "").lower()
                if q in desc:
                    score += 2
                for r in skill.get("rules", []):
                    if q in r.lower():
                        score += 1
                        break
                if score > 0:
                    results.append({"name": name, "score": score, "skill": skill})
        results.sort(key=lambda x: -x["score"])
        return results

    def skill_vfs_content(self) -> str:
        """Generate /skills/ virtual filesystem content."""
        lines = []
        for name in sorted(self._skills.keys()):
            skill = self._skills[name]
            desc = skill.get("description", "")[:50]
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
        body = content[m.end():]
        name = meta.get("name", os.path.basename(os.path.dirname(path)))
        data = {
            "name": name,
            "description": meta.get("description", str(meta.get("description", "")))[:200],
            "rules": self._extract_rules(body),
            "procedures": [],
            "knowledge": {"body": body[:2000]},
            "source": path,
            "allowed_tools": meta.get("allowed_tools"),
            "variables": meta.get("variables"),
            "prompt": body.strip(),
        }
        self._store(data, path)
        return True

    def _extract_rules(self, body: str) -> list[str]:
        """Extract DO/DON'T rules from markdown body."""
        rules = []
        import re
        for m in re.finditer(r"^[-*]\s+\*\*(DO|DON'T)\*\*:\s*(.+)$", body, re.MULTILINE):
            rules.append(f"{m.group(1)}: {m.group(2).strip()}")
        for m in re.finditer(r"^[-*]\s+(DO|DON'T)\s+(.+)$", body, re.MULTILINE):
            rules.append(f"{m.group(1)}: {m.group(2).strip()}")
        return rules

    def _store(self, data: dict, source: str = "") -> None:
        name = data.get("name", "unknown")
        data["source"] = source
        data["loaded_at"] = time.time()
        with self._lock:
            self._skills[name] = data


_manager: SkillManager | None = None


def get_skill_manager() -> SkillManager:
    global _manager
    if _manager is None:
        _manager = SkillManager()
    return _manager


def reset_skill_manager() -> None:
    global _manager
    _manager = None
