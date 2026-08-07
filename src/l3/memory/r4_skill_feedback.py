"""SkillFeedbackMixin — R4Agent retrieval + failure-trace intake.

Extracted from r4_agent.py (P0-2 split): the injection-retrieval surface
(get_lean_cases / get_lean_case_names / get_evolved_skills) and the
failure-trace pipeline (_track_failure / track_tool_failure /
_process_failure_traces).  Mixed into R4Agent alongside SkillEvolutionMixin;
cross-mixin calls (_atomic_write, _generalize_lean_cases,
_link_lean_graph_edge) resolve via the composed class.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import (
    R4_CARD_TAG_PREFIX,
    R4_EVOLVED_SKILLS_DEFAULT,
    R4_LEAN_CASES_DEFAULT,
    R4_REFLECTION_COOLDOWN,
    R4_REFLECTION_ENABLED,
    R4_REFLECTION_MAX_TOKENS,
    R4_REFLECTION_MIN_LEN,
    R4_RETRIEVAL_ENABLED,
    R4_RETRIEVAL_MIN_SCORE,
)
from l1.kernel.params.system import (
    LOG_TRUNC_30,
    LOG_TRUNC_40,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
)

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


class SkillFeedbackMixin:
    """SkillFeedbackMixin — lean-case retrieval and failure-trace intake."""

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

    def _track_failure(
        self,
        agent_id: str,
        tool_name: str,
        args: dict,
        error: str,
        turn_log: list[dict],
        domain: str = "",
        nature: str = "",
    ) -> None:
        """Record a tool call failure for later analysis and lean case generation.

        ``domain``/``nature`` are the driving card's context (from the tool
        pipeline's gate scope / card nature); they are persisted so the
        generated lean case can carry card-linkage tags.
        """
        try:
            import json
            import os

            from l1.kernel.params.system import SKILL_LEAN_CASE_TEMPLATE
            from l1.kernel.paths import get_paths as _gp

            lean_dir = _gp().skill_lean_dir
            entry = {
                "agent_id": agent_id,
                "tool": tool_name,
                "args": args,
                "error": error[:LOG_TRUNC_200],
                "timestamp": time.time(),
                "turn_count": len(turn_log),
                "resolved": False,
                "domain": domain[:LOG_TRUNC_40],
                "nature": nature[:LOG_TRUNC_40],
            }
            os.makedirs(lean_dir, exist_ok=True)
            fp = os.path.join(
                lean_dir, SKILL_LEAN_CASE_TEMPLATE.format(agent_id=agent_id, tool_name=tool_name, ts=int(time.time()))
            )
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2)
            # R4 archive: persist the raw failure trace so a generated lean case
            # can be traced back to "why it exists" (audit trail).
            try:
                from l3.tools._archive import _cmd_archive_store

                _cmd_archive_store(
                    fonds="skills",
                    series="lean_trace",
                    content=json.dumps(entry, ensure_ascii=False)[:LOG_TRUNC_2000],
                    tags=f"{agent_id},{tool_name},failure",
                )
            except Exception as e:
                logger.debug("R4Agent: archive failure trace skipped: %s", e)
        except Exception as e:
            logger.warning("R4Agent: track failure failed: %s", e)

    def track_tool_failure(
        self, agent_id: str, tool_name: str, args: dict, error: str, turn_log: list[dict],
        domain: str = "", nature: str = "",
    ) -> None:
        """Public entry point for tool-pipeline failure recording."""
        self._track_failure(agent_id, tool_name, args, error, turn_log, domain=domain, nature=nature)

    def _process_failure_traces(self) -> int:
        """Scan pending failure traces and generate lean case Skill entries.

        Features:
          - Deduplication: same tool+agent entries are merged into one lean case.
          - Atomic write: resolved flag is written via tempfile+rename.
          - Refine hints: a new failure hitting an evolved skill of the same
            tool emits a hint for re-evolution (never auto-rewrites).
        """
        import json
        import os

        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager

        lean_dir = _gp().skill_lean_dir
        processed = 0
        try:
            if not os.path.isdir(lean_dir):
                return 0
            sm = get_skill_manager()
            # Collect existing lean case names for dedup
            existing = set()
            for s in sm.list_skills(tags=["lean_case"]):
                existing.add(s.get("name", ""))

            for fn in os.listdir(lean_dir):
                if not fn.endswith(".json"):
                    continue
                fp = os.path.join(lean_dir, fn)
                try:
                    with open(fp, encoding="utf-8") as f:
                        entry = json.load(f)
                    if entry.get("resolved"):
                        continue
                    tool = entry["tool"]
                    agent = entry.get("agent_id", "unknown")
                    # Deduplication: skip if a lean case for this tool+agent already
                    # exists.  Exact or prefix match only — a raw substring test
                    # would falsely drop patterns for tools with shared prefixes
                    # (e.g. "rm" vs "rmdir").
                    dedup_key = f"lean_{agent}_{tool}"
                    if any(n == dedup_key or n.startswith(dedup_key + "_") for n in existing):
                        entry["resolved"] = True
                        self._atomic_write(fp, entry)
                        continue

                    # Generate lean case: "tool X failed with error Y because of Z"
                    lean_text = (
                        f"When using {tool} with {entry['args']}, "
                        f"it failed: {entry['error']}. "
                        f"Avoid this pattern after {entry['turn_count']} turns."
                    )
                    # Better naming: lean_{agent}_{tool}_{error_stem}
                    error_stem = entry.get("error", "unknown")[:LOG_TRUNC_30].replace(" ", "_")
                    skill_name = dedup_key
                    if error_stem:
                        skill_name = f"{dedup_key}_{error_stem}"
                    # Card linkage: carry the originating card's nature/domain
                    # as card: prefixed tags so retrieval can surface this case
                    # when a card of the same nature/domain executes.
                    case_tags = ["lean_case", "failure", agent, tool]
                    _nature = str(entry.get("nature", "") or "")
                    _domain = str(entry.get("domain", "") or "")
                    if _nature:
                        case_tags.append(f"{R4_CARD_TAG_PREFIX}{_nature}")
                    if _domain:
                        case_tags.append(f"{R4_CARD_TAG_PREFIX}{_domain}")
                    sm.create(
                        name=skill_name,
                        description=f"Failure case: {tool} — {entry['error'][:LOG_TRUNC_60]}",
                        prompt=lean_text,
                        tags=case_tags,
                        allowed_tools=[tool],
                        internal=True,
                    )
                    # Track the newly created name so duplicate traces in the
                    # same scan are skipped instead of overwriting it.
                    existing.add(skill_name)
                    # P2-2: signal when a new failure hits an evolved skill that
                    # allows the same tool — refine hint for re-evolution.
                    # Never auto-rewrites the skill (updates are gated).
                    try:
                        for h in sm.list_by_allowed_tools(tool):
                            # list_by_allowed_tools returns name/description
                            # only — fetch the full record for the tag check.
                            full = sm.get(h["name"]) or {}
                            if "evolved" in (full.get("tags") or []):
                                if self._pmu:
                                    try:
                                        self._pmu.increment("skills.refine_hint")
                                    except Exception:
                                        logger.debug("R4Agent: pmu increment failed, skipped", exc_info=True)
                                logger.info(
                                    "R4Agent: failure for %s hits evolved skill '%s' — refine hint", tool, h["name"]
                                )
                                break
                    except Exception:
                        logger.debug("R4Agent: refine hint scan failed", exc_info=True)
                    # R5 graph: lean case `depends_on` the failing tool skill
                    # (if one exists) — non-blocking, graph may be disabled.
                    self._link_lean_graph_edge(tool, skill_name)
                    if self._pmu:
                        try:
                            self._pmu.increment("skills.lean.generated")
                        except Exception:
                            logger.debug("R4Agent: pmu increment failed, skipped", exc_info=True)
                    entry["resolved"] = True
                    self._atomic_write(fp, entry)
                    processed += 1
                except Exception as e:
                    logger.warning("R4Agent: process trace %s failed: %s", fn, e)
        except Exception as e:
            logger.warning("R4Agent: process failure traces failed: %s", e)
        if processed > 0:
            try:
                self._generalize_lean_cases(sm)
            except Exception as e:
                logger.warning("R4Agent: generalize lean cases failed: %s", e)
        return processed

    def reflect_failure(self, tool: str, cases: list[dict]) -> str | None:
        """Reflexion-style attribution: distill failures into why/fix/pattern.

        LLM-reflects on a tool's lean cases, producing a structured insight
        (root cause, fix, canonical pattern) recorded to the reference
        channel for correlation.  Gated by ``R4_REFLECTION_ENABLED`` and a
        per-tool cooldown; any failure (LLM error, invalid JSON, below the
        length floor) returns None so callers keep the raw baseline.  Never
        writes skills — the caller owns the write.
        """
        import json as _json

        if not R4_REFLECTION_ENABLED:
            return None
        now = time.time()
        if now - self._last_reflect.get(tool, 0.0) < R4_REFLECTION_COOLDOWN:
            logger.debug("R4Agent: failure reflection for %s skipped (cooldown)", tool)
            return None
        digest = "\n".join(f"- {c.get('prompt', '')[:LOG_TRUNC_200]}" for c in cases)
        prompt = (
            "These are repeated failures for one tool. Reflect on the root "
            f"cause and the fix, naming a canonical pattern.\n{digest}\n"
            'Reply with JSON only: {"why": "<root cause>", '
            '"fix": "<how to fix>", "pattern": "<pattern-name>"}'
        )
        try:
            from l4.llm.llm import get_engine

            engine = get_engine()
            result = engine.generate(
                prompt=prompt,
                system="You are a failure analyst for an agent operating system.",
                max_tokens=R4_REFLECTION_MAX_TOKENS,
                user_id="r4-agent",
            )
        except Exception as e:
            logger.warning("R4Agent: failure reflection failed: %s", e)
            self._last_reflect[tool] = now
            return None
        self._last_reflect[tool] = now
        content = (result.get("content") or "").strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()
        try:
            data = _json.loads(content)
            why = data.get("why", "") if isinstance(data, dict) else ""
            fix = data.get("fix", "") if isinstance(data, dict) else ""
            pattern = data.get("pattern", "") if isinstance(data, dict) else ""
        except Exception as e:
            logger.warning("R4Agent: failure reflection invalid JSON for %s: %s", tool, e)
            return None
        why = str(why).strip() if isinstance(why, str) else ""
        fix = str(fix).strip() if isinstance(fix, str) else ""
        pattern = str(pattern).strip() if isinstance(pattern, str) else ""
        if len(why) + len(fix) < R4_REFLECTION_MIN_LEN:
            logger.info("R4Agent: failure reflection for %s rejected (too short)", tool)
            return None
        # Record the attribution to the reference channel (audit/correlation).
        try:
            from l3.bus.reference_channel import get_rc

            get_rc().event(
                "anomaly",
                {"tool": tool, "why": why, "fix": fix, "pattern": pattern},
                source="r4-reflection",
            )
        except Exception as e:
            logger.debug("R4Agent: failure reflection RC record failed: %s", e)
        if self._pmu:
            try:
                self._pmu.increment("skills.reflections.recorded")
            except Exception:
                logger.debug("R4Agent: pmu increment failed, skipped", exc_info=True)
        return f"{pattern}: {why} Fix: {fix}"

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
        skills = sm.list_skills(tags=tags, limit=limit * 2, sort_by="loaded_at")
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
                                }
                            )
                    if evolved:
                        return evolved[:limit]
            except Exception as e:
                logger.debug("R4Agent: graph diffusion fallback to linear: %s", e)
        skills = sm.list_skills(tags=["evolved"], limit=limit * 2, sort_by="loaded_at")
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
        if not R4_RETRIEVAL_ENABLED or not query:
            return self.get_evolved_skills(
                agent_id=agent_id, cell_id=cell_id, limit=limit, graph_diffusion=graph_diffusion, tags=tags
            )
        base = self.get_evolved_skills(
            agent_id=agent_id, cell_id=cell_id, limit=limit * 4, graph_diffusion=graph_diffusion, tags=tags
        )
        if not base:
            return []
        from l3.memory.skill_retriever import get_retriever

        ranked = get_retriever().rank(query, base, limit=limit, min_score=R4_RETRIEVAL_MIN_SCORE)
        return ranked if ranked else base[:limit]
