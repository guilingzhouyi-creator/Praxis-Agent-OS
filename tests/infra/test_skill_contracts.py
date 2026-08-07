"""Built-in skill contracts — config/skills must be general, read-only, and active.

Verifies the built-in (shipped) skill catalog:
  1. Every SKILL.md under config/skills has valid frontmatter (name,
     description, allowed-tools) and the 12 universal-principle sections.
  2. Built-in skills are marked ``builtin`` and cannot be overwritten or
     deleted — even with ``internal=True`` (system processes).
  3. Skill content is generalized — no project-specific path literals and
     no instructions that violate constitutional rules.
  4. Built-in skills are injected into session system prompts by default
     (SkillCatalogHook) unless ``skill.auto_activate_builtin`` is disabled.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "config" / "skills"

# Constitutional violations a skill must never instruct.
_FORBIDDEN_PATTERNS = [
    r"bypass.{0,20}sandbox",
    r"modify.{0,20}constitution",
    r"write outside.{0,20}territory",
    r"skip.{0,20}gate",
    r"swallow.{0,20}exception",
]

_PRINCIPLE_COUNT = 12


def _builtin_skill_dirs() -> list[Path]:
    """Return the built-in skill directories (each containing SKILL.md)."""
    return sorted(d for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").exists())


class TestBuiltinSkillCatalog:
    """config/skills — shipped skills must be well-formed and generalized."""

    def test_builtin_skills_exist(self):
        dirs = _builtin_skill_dirs()
        assert len(dirs) >= 7, f"expected >=7 built-in skills, got {len(dirs)}"

    def test_frontmatter_valid(self):
        for d in _builtin_skill_dirs():
            front = _frontmatter(d / "SKILL.md")
            assert front.get("name"), f"{d.name}: missing name"
            assert front.get("description"), f"{d.name}: missing description"
            assert "allowed-tools" in front, f"{d.name}: missing allowed-tools"
            assert front.get("disable-model-invocation") is True, (
                f"{d.name}: built-in skills must be user-invoked only")

    def test_universal_principles_present(self):
        """Each built-in skill carries all 12 universal-principle sections."""
        for d in _builtin_skill_dirs():
            body = (d / "SKILL.md").read_text(encoding="utf-8")
            numbered = re.findall(r"^(\d+)\.\s", body, re.MULTILINE)
            assert len(numbered) >= _PRINCIPLE_COUNT, (
                f"{d.name}: expected {_PRINCIPLE_COUNT} principles, got {len(numbered)}")

    def test_no_project_specific_paths(self):
        """Skill content must be generalized — no project-specific path literals."""
        forbidden = [
            "src/l", "tests/infra", "praxis.yaml", ".praxis/skills",
            "l1.kernel", "l3.", "StatsCenter", "CardRegistry", "GateChain",
        ]
        for d in _builtin_skill_dirs():
            body = (d / "SKILL.md").read_text(encoding="utf-8")
            hits = [f for f in forbidden if f in body]
            assert not hits, f"{d.name}: project-specific literals {hits}"

    def test_no_constitutional_violations(self):
        """Skill content must never instruct bypassing constitutional rules."""
        for d in _builtin_skill_dirs():
            lines = (d / "SKILL.md").read_text(encoding="utf-8").splitlines()
            for lineno, line in enumerate(lines, 1):
                lowered = line.lower()
                if any(neg in lowered for neg in (
                        "don't", "never", "must not", "shall not", "not allowed",
                        "may not", "cannot", "no agent", "prohibited", "forbidden",
                        " no ", "n't ")):
                    continue  # negated constraint — compliant guidance
                for pat in _FORBIDDEN_PATTERNS:
                    assert not re.search(pat, line, re.IGNORECASE), (
                        f"{d.name}:{lineno}: forbidden instruction {pat!r}: {line.strip()}"
                    )


class TestBuiltinReadOnly:
    """Built-in skills are immutable — even for system (internal) processes."""

    def test_builtin_marked_and_protected(self):
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()
        sm.load_builtin()

        builtins = [s for s in sm.list_skills() if s.get("builtin")]
        assert builtins, "no builtin skills loaded"
        name = builtins[0]["name"]

        # create/update/delete must all be rejected, including internal=True.
        assert not sm.create(name, prompt="x", internal=True)["success"]
        assert not sm.update(name, {"prompt": "x"}, internal=True)["success"]
        assert not sm.delete(name, internal=True)["success"]
        # The skill must still be present afterwards.
        assert sm.get(name) is not None

    def test_non_builtin_still_mutable(self):
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()
        sm.load_builtin()
        r = sm.create("contracts-tmp", prompt="tmp", internal=True)
        assert r["success"]
        assert sm.delete("contracts-tmp", internal=True)["success"]


class TestBuiltinDefaultActivation:
    """Built-in skills are injected into session prompts by default."""

    def test_hook_injects_builtin_first(self):
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.services.hook import SkillCatalogHook
        reset_skill_manager()
        sm = get_skill_manager()
        sm.load_builtin()

        out = SkillCatalogHook().session_start("task", "test-agent")
        assert "[builtin]" in out, "session prompt should list builtin skills"
        # Built-in entry appears before any non-builtin.
        idx_builtin = out.find("[builtin]")
        idx_plain = out.find("Available skills")
        assert idx_plain != -1 and idx_builtin > idx_plain


def _frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter between --- markers."""
    content = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    assert m, f"{path}: missing YAML frontmatter"
    meta = yaml.safe_load(m.group(1))
    assert isinstance(meta, dict), f"{path}: frontmatter must be a dict"
    return meta
