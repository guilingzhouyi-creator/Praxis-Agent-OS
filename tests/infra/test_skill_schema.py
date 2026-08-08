"""Skill catalog schema conformance — normalization gate for config/skills.

Enforces the normalized frontmatter contract across every builtin SKILL.md:
required fields, enum validity, dangling ``next``/``dependencies`` references,
guidance-DAG acyclicity and loader round-trip of the new fields
(disclosure/stages/next). This gate makes future catalog edits conform
instead of drifting — the enforcement half of the skill-file normalization.
"""

from __future__ import annotations

import glob
import os

import pytest
import yaml

from l1.kernel.skill import get_skill_manager, reset_skill_manager

SKILLS_DIR = "config/skills"

AUDIENCE_TAGS = {"strategy", "execution"}
DISCLOSURE_VALUES = {"full", "index", "none"}
POSTURE_VALUES = {"productive", "offensive"}


def _skill_files() -> list[str]:
    """All builtin SKILL.md files under config/skills (sorted)."""
    return sorted(glob.glob(f"{SKILLS_DIR}/*/SKILL.md"))


def _frontmatter(path: str) -> dict:
    """Parse the YAML frontmatter of a SKILL.md file."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    parts = text.split("---", 2)
    assert len(parts) > 1, f"{path}: missing frontmatter delimiters"
    return yaml.safe_load(parts[1]) or {}


@pytest.fixture(autouse=True)
def _reset_and_load():
    """Fresh SkillManager with the real builtin catalog for every test."""
    reset_skill_manager()
    get_skill_manager().load_dir(SKILLS_DIR)
    yield
    reset_skill_manager()


class TestSchemaRequiredFields:
    """Every builtin skill must declare the full normalized frontmatter."""

    REQUIRED = (
        "name",
        "description",
        "tags",
        "disable-model-invocation",
        "posture",
        "allowed-tools",
        "disclosure",
    )

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_required_fields_present(self, path):
        meta = _frontmatter(path)
        for field in self.REQUIRED:
            assert field in meta, f"{path}: missing '{field}'"

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_enum_validity(self, path):
        meta = _frontmatter(path)
        assert meta["posture"] in POSTURE_VALUES, f"{path}: bad posture '{meta['posture']}'"
        assert meta["disclosure"] in DISCLOSURE_VALUES, f"{path}: bad disclosure '{meta['disclosure']}'"
        audience = set(meta.get("tags") or []) & AUDIENCE_TAGS
        assert len(audience) <= 1, f"{path}: conflicting audience tags {audience}"

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_description_trigger_oriented(self, path):
        desc = _frontmatter(path)["description"]
        assert desc.startswith("Use when"), f"{path}: description must be trigger-oriented ('Use when …')"

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_name_matches_directory(self, path):
        meta = _frontmatter(path)
        assert meta["name"] == os.path.basename(os.path.dirname(path)), f"{path}: name ≠ directory"


class TestSchemaReferences:
    """next/dependencies must reference skills that actually exist."""

    def test_no_dangling_references(self):
        sm = get_skill_manager()
        known = {s["name"] for s in sm.list_skills()}
        for path in _skill_files():
            meta = _frontmatter(path)
            for ref in list(meta.get("dependencies") or []) + list(meta.get("next") or []):
                assert ref in known, f"{path}: dangling reference '{ref}'"

    def test_guidance_graph_acyclic(self):
        r = get_skill_manager().validate_guidance_graph()
        assert r["acyclic"] is True, f"guidance graph cycles: {r['cycles']}"


class TestSchemaRoundTrip:
    """Loader round-trip preserves the normalized fields."""

    def test_full_frontmatter_round_trip(self, tmp_path):
        skill_dir = tmp_path / "rt-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: rt-skill\n"
            "description: Use when testing round-trip\n"
            "tags: [execution]\n"
            "disable-model-invocation: true\n"
            "posture: productive\n"
            "disclosure: index\n"
            "allowed-tools: [read_file]\n"
            "next: [code-review]\n"
            "stages:\n"
            "  - id: one\n"
            "    instructions: do one\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        sm = get_skill_manager()
        sm.load_dir(str(tmp_path))
        skill = sm.get("rt-skill")
        assert skill["disclosure"] == "index"
        assert skill["next"] == ["code-review"]
        assert skill["stages"][0]["id"] == "one"


class TestSchemaBodyLayout:
    """Body section contract: Constitution Binding / Rules / Procedures present
    and parseable; universal principles live only in the shared layer."""

    def test_required_body_sections(self):
        for path in _skill_files():
            with open(path, encoding="utf-8") as f:
                body = f.read()
            assert "## Constitution Binding" in body, f"{path}: missing Constitution Binding"
            assert "## Rules" in body, f"{path}: missing Rules section"
            assert "## Procedures" in body, f"{path}: missing Procedures section"

    def test_no_universal_principles_residue(self):
        for path in _skill_files():
            with open(path, encoding="utf-8") as f:
                body = f.read()
            assert "## Universal Principles" not in body, f"{path}: principles must live in config/skills/_shared/"

    def test_rules_and_procedures_parse(self):
        sm = get_skill_manager()
        for path in _skill_files():
            name = os.path.basename(os.path.dirname(path))
            skill = sm.get(name)
            assert skill is not None, f"{path}: not loaded"
            assert skill.get("rules"), f"{path}: no parseable rules"
            assert skill.get("procedures"), f"{path}: no parseable procedures"
