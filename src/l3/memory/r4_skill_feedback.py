"""SkillFeedbackMixin — R4Agent retrieval + failure-trace intake.

Extracted from r4_agent.py (P0-2 split): the injection-retrieval surface
(get_lean_cases / get_lean_case_names / get_evolved_skills) and the
failure-trace pipeline (_track_failure / track_tool_failure /
_process_failure_traces).  Mixed into R4Agent alongside SkillEvolutionMixin;
cross-mixin calls (_atomic_write, _generalize_lean_cases,
_link_lean_graph_edge) resolve via the composed class.

This module composes two domain mixins from sibling files: trace
(failure recording + reflexion) and retrieval (injection surface).
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.agent import R4_EVOLVED_SKILLS_DEFAULT

from .r4_skill_retrieval import SkillRetrievalMixin
from .r4_skill_trace import SkillTraceMixin

logger = logging.getLogger(__name__)


class SkillFeedbackMixin(SkillTraceMixin, SkillRetrievalMixin):
    """SkillFeedbackMixin — lean-case retrieval and failure-trace intake.

    Composes the trace and retrieval domain mixins so the R4Agent sees one
    feedback surface.
    """

    # ── Attributes injected by the concrete R4Agent (see r4_agent.py) ──
    _skill_cache: dict[tuple, tuple]
    _last_reflect: dict[str, float]
    _pmu: Any

    def _generalize_lean_cases(self, sm: Any) -> int:
        """Generalize lean cases into skills (provided by SkillEvolutionMixin)."""
        raise NotImplementedError

    def _graph_diffuse_evolved(self, limit: int = R4_EVOLVED_SKILLS_DEFAULT) -> list[str]:
        """Diffuse evolved skills through the R5 graph (provided by SkillEvolutionMixin)."""
        raise NotImplementedError

    @staticmethod
    def _atomic_write(fp: str, data: dict) -> None:
        """Write JSON atomically (provided by R4Agent)."""
        raise NotImplementedError

    @staticmethod
    def _link_lean_graph_edge(tool: str, skill_name: str) -> None:
        """Link a lean case into the R5 graph (provided by SkillEvolutionMixin)."""
        raise NotImplementedError
