"""SkillEvolutionMixin — R4Agent skill evolution, persistence and summarization.

Extracted from r4_agent.py (P0-2 split): LLM skill evolution (evolve_skill),
rule-based generalization (_generalize_lean_cases), SKILL.md persistence
(_skill_md_path / _persist_skill_md), LLM lesson summarization
(_summarize_tool_lessons), archive/audit hooks (_archive_before_evolve,
_link_lean_graph_edge), and TTL lifecycle (_prune_stale_skills /
_clean_orphan_traces / _graph_diffuse_evolved).

Module helpers that remain in r4_agent.py (_resolve_skill_scope,
_resolve_model_spec) are imported lazily inside the methods to avoid a
circular import — by call time the r4_agent module is fully loaded.

This module composes four domain mixins from sibling files: persist
(SKILL.md + archive), distill (LLM summarization/distillation), lifecycle
(TTL/conflict/curation), and generalize (lean-case consolidation +
evolve_skill).
"""

from __future__ import annotations

import logging
import re as _re
from typing import Any

from .r4_skill_distill import SkillDistillMixin
from .r4_skill_generalize import SkillGeneralizeMixin
from .r4_skill_lifecycle import SkillLifecycleMixin
from .r4_skill_persist import SkillPersistMixin

logger = logging.getLogger(__name__)


def _scrub_skill_prompt(prompt: str, violations: list[str]) -> str:
    """Drop lines from a prompt that carry contract violations.

    Line-level scrub: removes any line matching a forbidden constitutional
    pattern or containing a project-specific literal, so the surviving body
    stays usable. Returns the scrubbed prompt (may be empty → caller
    rejects).
    """
    from l1.kernel.params.system import (
        SKILL_CONTRACT_FORBIDDEN_PATHS,
        SKILL_CONTRACT_FORBIDDEN_PATTERNS,
    )

    kept: list[str] = []
    for line in (prompt or "").splitlines():
        bad = False
        for pat in SKILL_CONTRACT_FORBIDDEN_PATTERNS:
            if _re.search(pat, line, _re.IGNORECASE):
                bad = True
                break
        if not bad:
            for lit in SKILL_CONTRACT_FORBIDDEN_PATHS:
                if lit in line:
                    bad = True
                    break
        if not bad:
            kept.append(line)
    return "\n".join(kept).strip()


class SkillEvolutionMixin(SkillPersistMixin, SkillDistillMixin, SkillLifecycleMixin, SkillGeneralizeMixin):
    """SkillEvolutionMixin — skill evolution, persistence and summarization.

    Composes the persist/distill/lifecycle/generalize domain mixins so the
    R4Agent sees one skill-evolution surface.
    """

    # ── Attributes injected by the concrete R4Agent (see r4_agent.py) ──
    agent_id: str
    _last_summarize: dict[str, float]
    _last_summarize_any: float
    _last_distill: dict[str, float]
    _pmu: Any

    def reflect_failure(self, tool: str, cases: list[dict]) -> str | None:
        """Reflexion-style attribution (provided by SkillFeedbackMixin)."""
        raise NotImplementedError
