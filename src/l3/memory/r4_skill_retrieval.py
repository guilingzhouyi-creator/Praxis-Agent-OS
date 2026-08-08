"""SkillRetrievalMixin — lean-case / evolved-skill retrieval surface.

Extracted from r4_skill_feedback.py (SkillFeedbackMixin): the injection
retrieval surface (get_lean_cases / get_lean_case_names /
get_evolved_skills / retrieve_skills) plus the card-tag gate helper.
Composed by SkillFeedbackMixin.
"""

from __future__ import annotations

import logging

from l1.kernel.params.agent import (
    R4_CARD_TAG_PREFIX,
    R4_EVOLVED_SKILLS_DEFAULT,
    R4_LEAN_CASES_DEFAULT,
    R4_RETRIEVAL_ENABLED,
    R4_RETRIEVAL_MIN_SCORE,
)
from l1.kernel.params.system import SKILL_POSTURE_DEFAULT

logger = logging.getLogger(__name__)


def _passes_card_tags(skill: dict, tags: list[str] | None) -> bool:
    """Card-tag gate: untagged skills are universal; tagged skills must match.

    ``tags`` are OR-matched against the skill's ``card:*`` tags.  A skill
    carrying no ``card:*`` tag passes regardless (system knowledge stays
    visible to every card type); a skill tagged for another card type is
    excluded from this card's retrieval.
    """
    if not tags:
        return True
    skill_tags = set(skill.get("tags") or [])
    tagged = {t for t in skill_tags if t.startswith(R4_CARD_TAG_PREFIX)}
    if not tagged:
        return True
    return bool(tagged & set(tags))


class SkillRetrievalMixin:
    """Lean-case and evolved-skill retrieval for AgentLoop injection."""

    def get_lean_cases(
        self, agent_id: str = "", tool_name: str = "", cell_id: str = "", limit: int = R4_LEAN_CASES_DEFAULT
    ) -> list[str]:
        """Retrieve lean failure cases for injection into AgentLoop prompts.

        When ``cell_id`` has a bound skill white-list (via SkillManager
        cell_skill_map), only lean cases whose name is in the white-list are
        returned; unbound cells fall back to the global pool.
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        cache_key = ("lean", agent_id, tool_name, cell_id, limit)
        rev = sm.revision()
        cached = self._skill_cache.get(cache_key)
        if cached and cached[0] == rev:
            return cached[1]
        tags = ["lean_case"]
        if agent_id:
            tags.append(agent_id)
        if tool_name:
            tags.append(tool_name)
        skills = sm.list_skills(tags=tags, limit=limit * 2, sort_by="loaded_at", include_prompt=True)
        allow = sm.skills_for_cell(cell_id) if cell_id else set()
        result = []
        names = []
        for s in skills:
            if allow and s["name"] not in allow:
                continue
            if s.get("prompt"):
                names.append(s["name"])
                result.append(s["prompt"])
            if len(result) >= limit:
                break
        result = result[:limit]
        names = names[:limit]
        self._skill_cache[cache_key] = (rev, result, names)
        return result

    def get_lean_case_names(
        self, agent_id: str = "", tool_name: str = "", cell_id: str = "", limit: int = R4_LEAN_CASES_DEFAULT
    ) -> list[str]:
        """Return the skill names behind the lean cases get_lean_cases() yields.

        Shares the injection cache with get_lean_cases() so the AgentLoop can
        refresh ``last_used`` for exactly the cases it injected — no extra
        registry scan.
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        cache_key = ("lean", agent_id, tool_name, cell_id, limit)
        rev = sm.revision()
        cached = self._skill_cache.get(cache_key)
        if cached and cached[0] == rev and len(cached) >= 3:
            return cached[2]
        # Cache miss or stale — repopulate through get_lean_cases().
        self.get_lean_cases(agent_id, tool_name, cell_id, limit)
        cached = self._skill_cache.get(cache_key)
        return cached[2] if cached and len(cached) >= 3 else []

    def get_evolved_skills(
        self,
        agent_id: str = "",
        cell_id: str = "",
        limit: int = R4_EVOLVED_SKILLS_DEFAULT,
        graph_diffusion: bool = False,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Retrieve evolved skills for injection into AgentLoop prompts.

        Filters by agent_id if provided (strict tag membership, not OR-match).
        When ``cell_id`` has a bound white-list, only white-listed skills are
        returned (unbound cells fall back to the global pool).  ``tags`` are
        OR-matched against the skill's tags (card-nature linkage: skills
        tagged ``card:<nature>`` surface only for cards of that nature).
        Returns most recently loaded skills first.
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        cache_key = ("evolved", agent_id, cell_id, limit, graph_diffusion, tuple(tags or ()))
        rev = sm.revision()
        cached = self._skill_cache.get(cache_key)
        if cached and cached[0] == rev:
            return cached[1]
        allow = sm.skills_for_cell(cell_id) if cell_id else set()
        if graph_diffusion:
            try:
                diffused = self._graph_diffuse_evolved(limit=limit)
                if diffused:
                    evolved = []
                    for name in diffused:
                        s = sm.get(name)
                        if s and s.get("prompt"):
                            if allow and name not in allow:
                                continue
                            if not _passes_card_tags(s, tags):
                                continue
                            evolved.append(
                                {
                                    "name": s["name"],
                                    "description": s.get("description", ""),
                                    "prompt": s["prompt"],
                                    "posture": s.get("posture", SKILL_POSTURE_DEFAULT),
                                }
                            )
                    if evolved:
                        return evolved[:limit]
            except Exception as e:
                logger.debug("R4Agent: graph diffusion fallback to linear: %s", e)
        skills = sm.list_skills(tags=["evolved"], limit=limit * 2, sort_by="loaded_at", include_prompt=True)
        evolved = []
        for s in skills:
            if agent_id and agent_id not in s.get("tags", []):
                continue
            if allow and s["name"] not in allow:
                continue
            if not _passes_card_tags(s, tags):
                continue
            if s.get("prompt"):
                evolved.append(
                    {
                        "name": s["name"],
                        "description": s.get("description", ""),
                        "prompt": s["prompt"],
                        "posture": s.get("posture", SKILL_POSTURE_DEFAULT),
                    }
                )
        evolved = evolved[:limit]
        self._skill_cache[cache_key] = (rev, evolved)
        return evolved

    def retrieve_skills(
        self,
        query: str = "",
        agent_id: str = "",
        cell_id: str = "",
        limit: int = R4_EVOLVED_SKILLS_DEFAULT,
        graph_diffusion: bool = False,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Retrieve evolved skills ranked by task-text similarity.

        Delegates ranking to the pluggable retriever backend (``tfidf`` by
        default, see ``l3.memory.skill_retriever``).  Gated by
        ``R4_RETRIEVAL_ENABLED``; when disabled, query is empty, or no
        candidate clears the similarity floor, it falls back to
        ``get_evolved_skills`` ordering (most recently loaded first).
        ``tags`` are forwarded as an OR-match filter (card-nature linkage).
        """
        # Runtime policy (SkillManager pipeline policy) overrides the
        # compile-time defaults — retrieval can be disabled or its similarity
        # floor tuned per-deployment via API / L2 Shell, not just params.
        policy = {}
        try:
            from l1.kernel.skill import get_skill_manager

            policy = get_skill_manager().pipeline_policy()
        except Exception:
            pass
        retrieval_enabled = bool(policy.get("retrieval", R4_RETRIEVAL_ENABLED))
        min_score = float(policy.get("retrieval_min_score", R4_RETRIEVAL_MIN_SCORE))
        if not retrieval_enabled or not query:
            return self.get_evolved_skills(
                agent_id=agent_id, cell_id=cell_id, limit=limit, graph_diffusion=graph_diffusion, tags=tags
            )
        base = self.get_evolved_skills(
            agent_id=agent_id, cell_id=cell_id, limit=limit * 4, graph_diffusion=graph_diffusion, tags=tags
        )
        if not base:
            return []
        # Disclosure depth: skills marked disclosure=none never surface in
        # task-similarity retrieval (explicit use_skill only).
        base = [s for s in base if s.get("disclosure", "full") != "none"]
        if not base:
            return []
        # Builtin skills join the task-similarity pool (audience + disclosure
        # filtered) so retrieval covers the full catalog, not just evolved.
        try:
            from l1.kernel.skill import get_skill_manager as _loop_sm
            from l1.kernel.skill import skill_visible as _sv

            # Full guidance mode: skills with *unmet hard dependencies* stay
            # out of the retrieval pool; soft dependencies are advisory and
            # never lock a skill (no builtin declares hard deps, so the pool
            # keeps full coverage by default).
            _hard_locked = set()
            if _loop_sm().guidance_policy().get("mode", "full") == "full":
                for s2 in _loop_sm().list_skills():
                    if s2.get("dependency_kind", "soft") == "hard" and (s2.get("dependencies") or []):
                        _hard_locked.add(s2.get("name"))
            for s in _loop_sm().list_skills(include_prompt=True):
                if not s.get("builtin"):
                    continue
                if s.get("disclosure", "full") == "none":
                    continue
                if not _sv(s, agent_id):
                    continue
                if s.get("name") in _hard_locked:
                    continue
                if s not in base:
                    base.append(s)
        except Exception:
            pass
        if not base:
            return []
        from l3.memory.skill_retriever import get_retriever

        ranked = get_retriever().rank(query, base, limit=limit, min_score=min_score)
        return ranked if ranked else base[:limit]
