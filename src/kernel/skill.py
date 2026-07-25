"""Skill system — loadable agent capabilities.

Skills are YAML/Markdown files that define:
  - Knowledge: architecture, conventions, domain expertise
  - Rules: coding standards, review criteria, testing requirements
  - Procedures: step-by-step workflows

Skills are mounted in VFS at /skills/ and agents can query them.

Usage:
  from kernel.skill import get_skill_manager
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


@dataclass
class Skill:
    name: str
    description: str = ""
    rules: list[str] = field(default_factory=list)
    procedures: list[dict] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    loaded_at: float = 0.0


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
        """Load built-in skills from default search paths."""
        count = 0
        import kernel
        kernel_dir = os.path.dirname(kernel.__file__)
        for sd in SKILL_DIRS:
            path = os.path.join(os.path.dirname(kernel_dir), sd)
            count += self.load_dir(path)
            path2 = os.path.join(os.path.dirname(kernel_dir), "..", sd)
            if os.path.isdir(path2):
                count += self.load_dir(path2)
        # Also load evolved skills from data directory
        try:
            from kernel.params import SKILL_EVOLVED_DIR
            if os.path.isdir(SKILL_EVOLVED_DIR):
                count += self.load_dir(SKILL_EVOLVED_DIR)
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
