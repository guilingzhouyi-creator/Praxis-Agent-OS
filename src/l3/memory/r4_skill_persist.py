"""SkillPersistMixin — SKILL.md persistence, archive hooks, and graph links.

Extracted from r4_skill_evolution.py (SkillEvolutionMixin): the layered
SKILL.md writer with round-trip frontmatter (_skill_md_path /
_persist_skill_md), skill-directory removal, pre-evolution archiving, and
non-blocking R5 graph edge helpers. Composed by SkillEvolutionMixin.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.system import SKILL_POSTURE_DEFAULT, SKILL_POSTURE_VALID

logger = logging.getLogger(__name__)


class SkillPersistMixin:
    """SKILL.md persistence, archive hooks, and graph linkage helpers."""

    def _skill_md_path(self, name: str, scope: str = "") -> str:
        """Resolve the SKILL.md path for a skill in the evolved dir.

        Layered persistence: project scope → travels with the repo; global
        scope → machine-local data dir (must match the boot discovery dirs).
        An explicit ``scope`` ("project"/"global") overrides the configured
        default (``skill.evolve_scope``); empty string defers to config.
        """
        import os

        from l1.kernel.paths import get_paths as _gp
        from l3.memory.r4_agent import _resolve_skill_scope

        scope = scope or _resolve_skill_scope()
        evolved_base = _gp().skill_project_evolved_dir if scope == "project" else _gp().skill_evolved_dir
        return os.path.join(evolved_base, name, "SKILL.md")

    def _persist_skill_md(
        self,
        name: str,
        description: str,
        prompt: str,
        tags: list[str],
        allowed_tools: list[str] | None = None,
        rules: list[str] | None = None,
        procedures: list[dict] | None = None,
        variables: dict | None = None,
        disable_model_invocation: bool = False,
        dependencies: list[str] | None = None,
        dependency_kind: str = "soft",
        posture: str = SKILL_POSTURE_DEFAULT,
        scope: str = "",
    ) -> str:
        """Persist a skill as SKILL.md with round-trip frontmatter.

        Frontmatter carries name/description/tags/allowed_tools/variables/
        disable-model-invocation/dependencies/dependency-kind/posture so a
        reload via SkillManager._load_markdown() restores them; the prompt is
        the body. Shared by evolve_skill (LLM) and _generalize_lean_cases
        (rule-based) so both survive restart via the boot discovery dirs.  An
        explicit ``scope`` overrides the configured evolution scope for this
        write. Invalid ``posture`` values fall back to the safe default so a
        caller can never escalate a skill's posture through persistence.
        """
        import os

        import yaml as _yaml

        if posture not in SKILL_POSTURE_VALID:
            posture = SKILL_POSTURE_DEFAULT
        md_path = self._skill_md_path(name, scope)
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        meta: dict[str, Any] = {"name": name, "description": description, "tags": tags}
        if disable_model_invocation:
            meta["disable-model-invocation"] = True
        if dependencies:
            meta["dependencies"] = dependencies
        if dependency_kind != "soft":
            meta["dependency-kind"] = dependency_kind
        if posture != SKILL_POSTURE_DEFAULT:
            meta["posture"] = posture
        if allowed_tools:
            meta["allowed_tools"] = allowed_tools
        if variables:
            meta["variables"] = variables
        md_lines = ["---"]
        md_lines.append(_yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip())
        md_lines.append("---")
        md_lines.append("")
        md_lines.append(prompt)
        md_lines.append("")
        if rules:
            md_lines.append("## Rules")
            for rule in rules:
                # Batch 2: rules may be dicts carrying DPO preference
                # metadata — persist the rule text (metadata is runtime-only,
                # rebuilt by the next distillation from card signals).
                if isinstance(rule, dict):
                    md_lines.append(f"- {rule.get('rule', '')}")
                else:
                    md_lines.append(f"- {rule}")
            md_lines.append("")
        if procedures:
            md_lines.append("## Procedures")
            for proc in procedures:
                md_lines.append(f"- **{proc.get('step', '?')}**: {proc.get('description', '')}")
            md_lines.append("")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        return md_path

    @staticmethod
    def _fp_of(skill: dict) -> str:
        """Extract the case fingerprint from a generalized skill's description."""
        import re

        m = re.search(r"\[([0-9a-f]{12})\]$", skill.get("description", "") or "")
        return m.group(1) if m else ""

    @staticmethod
    def _archive_before_evolve(name: str, skill_data: dict) -> None:
        """R4 archive: persist a skill version before it is overwritten.

        Records the pre-evolution version under ``fonds="skills"``,
        ``series="evolved"`` as an audit / rollback baseline.  Non-blocking.
        """
        try:
            from l3.tools._archive import _cmd_archive_store

            _cmd_archive_store(
                fonds="skills",
                series="evolved",
                content=skill_data.get("prompt", "") or "",
                tags=f"{name},evolved,backup",
            )
        except Exception as e:
            logger.debug("R4Agent: archive pre-evolution version failed: %s", e)

    @staticmethod
    def _link_lean_graph_edge(tool: str, skill_name: str) -> None:
        """R5 graph: lean case ``depends_on`` the failing tool skill.

        Non-blocking — the graph defaults to off and failures are ignored.
        """
        try:
            from l3.memory.memory_graph import get_graph as _get_graph

            g = _get_graph()
            g.add_semantic_edge(from_id=tool, to_id=skill_name, relation="depends_on", created_by="r4-agent")
        except Exception as e:
            logger.debug("R4Agent: lean graph edge skipped: %s", e)

    def _remove_skill_dir(self, name: str) -> None:
        """Delete the persisted SKILL.md directory (project + global scopes)."""
        try:
            import os as _os
            import shutil

            from l1.kernel.paths import get_paths as _gp_paths

            _p = _gp_paths()
            for base in (_p.skill_project_evolved_dir, _p.skill_evolved_dir):
                skill_dir = _os.path.join(base, name)
                if _os.path.isdir(skill_dir):
                    shutil.rmtree(skill_dir, ignore_errors=True)
        except Exception as e:
            logger.debug("R4Agent: curated skill dir cleanup failed: %s", e)
