"""SkillGeneralizeMixin — rule-based generalization and LLM skill evolution.

Extracted from r4_skill_evolution.py (SkillEvolutionMixin): the lean-case
consolidation engine (_generalize_lean_cases) and the user-facing LLM skill
creation entry point (evolve_skill). Composed by SkillEvolutionMixin.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import (
    R4_CARD_TAG_MAX,
    R4_LEAN_GENERALIZE_THRESHOLD,
    SKILL_ARCHITECT_MAX_TOKENS,
)
from l1.kernel.params.system import (
    HASH_TRUNC_MEDIUM,
    SKILL_POSTURE_DEFAULT,
    SKILL_POSTURE_VALID,
)

logger = logging.getLogger(__name__)


class SkillGeneralizeMixin:
    """Lean-case generalization and LLM skill evolution."""

    def _generalize_lean_cases(self, sm: Any) -> int:
        """Merge per-tool lean cases into one generalized lessons skill.

        Rule-based generalization: once ``R4_LEAN_GENERALIZE_THRESHOLD`` lean
        cases share the same tool (grouped via ``allowed_tools``, falling back
        to the trailing tool tag for legacy cases), a single
        ``lean_{tool}_lessons`` skill consolidates their failure patterns.
        It carries the ``evolved`` tag so AgentLoop injects it via
        ``get_evolved_skills`` alongside LLM-evolved skills.
        """
        import hashlib
        import os

        # Master switch: generalization/distillation disabled at runtime
        # (API /config override) → skip entirely.
        try:
            from l1.kernel.skill import get_skill_manager as _sm_gate

            if not _sm_gate().distill_policy().get("distill", True):
                return 0
        except Exception:
            pass

        by_tool: dict[str, list[dict]] = {}
        for s in sm.list_skills(tags=["lean_case"]):
            tools = s.get("allowed_tools") or []
            tool = tools[0] if tools else (s.get("tags") or [""])[-1]
            if not tool:
                continue
            by_tool.setdefault(tool, []).append(s)

        generalized = 0
        for tool, cases in by_tool.items():
            # Reflexion-style attribution (non-blocking): distill the tool's
            # failures into why/fix/pattern and record to the reference
            # channel, independent of the lesson-synthesis threshold below.
            try:
                self.reflect_failure(tool, cases)
            except Exception as e:
                logger.debug("R4Agent: reflect_failure for %s skipped: %s", tool, e)
            if len(cases) < R4_LEAN_GENERALIZE_THRESHOLD:
                continue
            gen_name = f"lean_{tool}_lessons"
            # Batch 4: curriculum-style digest — semantic clustering
            # (shingle), frequency ordering and difficulty ramp via
            # _sample_digest; the fingerprint is computed over the sampled
            # digest so a stable case set stays idempotent.
            lessons = self._sample_digest(cases, tool)
            baseline = f"Known failure patterns when using {tool}:\n{lessons}"
            # Deterministic case fingerprint — idempotency is independent of
            # whether the stored prompt is LLM-summarized or rule-based, so a
            # refresh during the LLM cooldown never downgrades a refined lesson.
            fp = hashlib.md5(lessons.encode("utf-8")).hexdigest()[:HASH_TRUNC_MEDIUM]
            desc = f"Consolidated failure lessons for {tool} ({len(cases)} cases) [{fp}]"
            existing = sm.get(gen_name)
            if existing and self._fp_of(existing) == fp and os.path.exists(self._skill_md_path(gen_name)):
                continue  # same case set already generalized + persisted
            # Batch 2: preserve verified (non-deprecated) rules across
            # re-distillation — the digest carries them so the LLM keeps what
            # worked and only rewrites the deprecated ones. Deprecated rules
            # (preferred < R4_RULE_MIN_PREFERRED via card signals) are dropped.
            verified_context = ""
            if existing:
                ex_rules = existing.get("rules") or []
                if isinstance(ex_rules, list):
                    keep = []
                    for r in ex_rules:
                        if isinstance(r, str):
                            keep.append(r)
                        elif isinstance(r, dict) and not r.get("deprecated") and r.get("rule"):
                            keep.append(r["rule"])
                    if keep:
                        verified_context = "\nAlready-verified rules to KEEP (do not contradict):\n" + "\n".join(
                            f"- {r}" for r in keep
                        )
            # P3: LLM semantic summary (gated: threshold + per-tool cooldown +
            # per-tick throttle); any failure degrades to the rule-based baseline.
            llm_lesson = self._summarize_tool_lessons(tool, cases)
            # P4: full skill distillation — when the LLM is available, upgrade
            # the lessons into a structured skill definition (rules +
            # procedures) so the generalized skill carries enforceable
            # guidance, not just a prose paragraph. Falls back to the summary
            # (or baseline) on any failure; never blocks generalization.
            distilled = self._distill_lessons_skill(tool, cases, verified_context) if llm_lesson else None
            if distilled:
                candidate: str = distilled.get("prompt") or llm_lesson or baseline
                rules = distilled.get("rules") or []
                procs = distilled.get("procedures") or []
            else:
                candidate = llm_lesson if llm_lesson else baseline
                rules = []
                procs = []
            if existing:
                # P2-3: archive the pre-update version (audit/rollback baseline)
                # before overwriting — same guarantee evolve_skill gives.
                try:
                    self._archive_before_evolve(gen_name, existing)
                except Exception as e:
                    logger.warning("R4Agent: archive generalized skill failed: %s", e)
            sm.create(
                name=gen_name,
                description=desc,
                prompt=candidate,
                rules=rules,
                procedures=procs,
                tags=["evolved", tool],
                allowed_tools=[tool],
                internal=True,
            )
            try:
                self._persist_skill_md(
                    name=gen_name,
                    description=desc,
                    prompt=candidate,
                    tags=["evolved", tool],
                    allowed_tools=[tool],
                )
            except Exception as e:
                logger.warning("R4Agent: persist generalized skill %s failed: %s", gen_name, e)
            generalized += 1
        return generalized

    def evolve_skill(
        self, intent: str, cell_id: str = "", scope: str = "", extra_tags: list[str] | None = None
    ) -> dict:
        """Use LLM to generate a new skill definition from a natural language intent.

        Uses the LLM engine to produce a structured skill (name, description, rules,
        procedures, system prompt), then registers it with SkillManager and persists
        it as a SKILL.md file in the evolved skills directory.

        When ``cell_id`` is provided, the evolved skill is also bound to that
        Cell's white-list (演化即回灌) so its agents can inject it immediately.
        An explicit ``scope`` ("project"/"global") overrides the configured
        ``skill.evolve_scope`` for this evolution's SKILL.md write.
        ``extra_tags`` are appended to the LLM-generated tags (card-nature
        linkage: pass ``card:<nature>`` to make the skill hit cards of that
        nature).

        Invoked via: /skills evolve <intent>
        """
        if not intent or not intent.strip():
            return {"success": False, "error": "usage: /skills evolve <description>"}

        try:
            import json

            from l1.kernel.prompts import get_prompt
            from l1.kernel.skill import get_skill_manager
            from l4.llm.llm import get_engine

            system = get_prompt("r4_agent.skill_architect", "")
            prompt = f"Create a skill for: {intent.strip()}"
            engine = get_engine()
            from l3.memory.r4_agent import _resolve_model_spec
            from l3.services.model_service import get_service as _get_model_service

            model_kwargs = _get_model_service().resolve_dict(_resolve_model_spec())
            # Explicit kwargs take precedence — drop overlapping keys from the config dict.
            for _k in ("prompt", "system", "max_tokens", "user_id"):
                model_kwargs.pop(_k, None)
            result = engine.generate(
                prompt=prompt, system=system, max_tokens=SKILL_ARCHITECT_MAX_TOKENS, user_id="r4-agent", **model_kwargs
            )

            content = result.get("content", "").strip()
            # Strip any markdown fences if present
            if content.startswith("```"):
                lines = content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            skill_def = json.loads(content)
            name = skill_def.get("name", f"evolved-{int(time.time())}")

            # Register with SkillManager
            sm = get_skill_manager()

            # Check for existing skill with same name → versioning
            # Order matters: backup first, then overwrite-create. The old skill
            # is NOT deleted before the new one exists, so a failure between
            # steps never leaves the registry without the original skill.
            existing = sm.get(name)
            if existing:
                backup_name = f"{name}_v{int(time.time())}"
                # R4 archive: persist the pre-evolution version (audit/rollback baseline).
                self._archive_before_evolve(name, existing)
                sm.create(
                    name=backup_name,
                    description=(existing.get("description") or ""),
                    prompt=(existing.get("prompt") or ""),
                    tags=(existing.get("tags") or ["evolved"]) + ["backup"],
                    rules=existing.get("rules") or [],
                    procedures=existing.get("procedures") or [],
                    allowed_tools=existing.get("allowed_tools"),
                    internal=True,
                )

            # Normalize LLM output — type-guard every field so a malformed
            # response (prompt/description as dict, rules as non-str, …) cannot
            # corrupt the SKILL.md round-trip on reload.
            skill_tags = [str(t) for t in (skill_def.get("tags") or []) if isinstance(t, str)] + ["evolved"]
            if extra_tags:
                skill_tags += [t for t in extra_tags if isinstance(t, str) and t not in skill_tags][:R4_CARD_TAG_MAX]
            skill_desc = skill_def.get("description")
            skill_desc = skill_desc if isinstance(skill_desc, str) else ""
            skill_prompt = skill_def.get("prompt")
            skill_prompt = skill_prompt if isinstance(skill_prompt, str) else ""
            skill_rules = [r for r in (skill_def.get("rules") or []) if isinstance(r, str)]
            skill_procs = [p for p in (skill_def.get("procedures") or []) if isinstance(p, dict)]
            skill_tools = skill_def.get("allowed_tools")
            if not isinstance(skill_tools, list) or not all(isinstance(t, str) for t in skill_tools):
                skill_tools = None
            # Posture: carried through round-trip persistence; invalid values
            # from the LLM fall back to the safe default (productive).
            skill_posture = skill_def.get("posture", SKILL_POSTURE_DEFAULT)
            if skill_posture not in SKILL_POSTURE_VALID:
                skill_posture = SKILL_POSTURE_DEFAULT
            # Content contract (parity with the built-in catalog): a skill
            # that instructs constitutional violations or embeds
            # project-specific literals must not enter the registry. We
            # scrub the prompt (drop the violating lines) and, if the body
            # is left empty, reject the evolution entirely.
            from l1.kernel.skill import validate_skill_content as _validate_content
            from l3.memory.r4_skill_evolution import _scrub_skill_prompt

            violations = _validate_content(skill_prompt, skill_desc)
            if violations:
                logger.warning(
                    "R4Agent: evolved skill '%s' violates content contract, scrubbing: %s",
                    name,
                    "; ".join(violations),
                )
                skill_prompt = _scrub_skill_prompt(skill_prompt, violations)
                skill_desc = skill_desc if _validate_content(skill_prompt, skill_desc) == [] else ""
                if not skill_prompt.strip():
                    return {
                        "success": False,
                        "error": f"skill '{name}' rejected: content contract violations: {violations}",
                    }
            sm.create(
                name=name,
                description=skill_desc,
                prompt=skill_prompt,
                tags=skill_tags,
                rules=skill_rules,
                procedures=skill_procs,
                allowed_tools=skill_tools,
                posture=skill_posture,
                internal=True,
            )
            if existing:
                # Preserve usage counters across the overwrite — a re-evolve
                # must not reset usefulness tracking (TTL/quality signals).
                try:
                    sm.update(
                        name,
                        {
                            "useful_count": existing.get("useful_count", 0) or 0,
                            "last_used": existing.get("last_used", 0.0) or 0.0,
                        },
                    )
                except Exception as e:
                    logger.debug("R4Agent: restore usage counters failed: %s", e)

            # 演化即回灌: bind the evolved skill to the originating Cell so its
            # agents can inject it immediately (unbound → global pool).
            if cell_id:
                sm.bind_skill(cell_id, name)

            # R5 graph linkage: versioning creates a `refines` edge (old → new)
            # and a `type_chain` edge (same-agent evolution chain) when the
            # graph is enabled.  Non-blocking — graph defaults to off.
            try:
                from l3.memory.memory_graph import get_graph as _get_graph

                g = _get_graph()
                if existing:
                    g.add_semantic_edge(from_id=backup_name, to_id=name, relation="refines", created_by="r4-agent")
                g.remember_hook(
                    entry_id=name,
                    agent_id=self.agent_id,
                    entry_type="skill",
                    cell_id=cell_id,
                    recent=[{"id": backup_name, "entry_type": "skill", "agent_id": self.agent_id, "cell_id": cell_id}]
                    if existing
                    else [],
                    created_by="r4-agent",
                )
            except Exception as e:
                logger.debug("R4Agent: skill graph linkage skipped: %s", e)

            # Persist as SKILL.md — shared helper keeps round-trip frontmatter
            # (tags/allowed_tools/variables survive reload) for both the LLM
            # evolve path and the rule-based generalization path.
            from l3.memory.r4_agent import _resolve_skill_scope

            scope = scope or _resolve_skill_scope()
            self._persist_skill_md(
                name=name,
                description=skill_desc,
                prompt=skill_prompt,
                tags=skill_tags,
                allowed_tools=skill_tools,
                rules=skill_rules,
                procedures=skill_procs,
                variables=skill_def.get("variables"),
                posture=skill_posture,
                scope=scope,
            )

            if self._pmu:
                try:
                    self._pmu.increment("skills.evolved.created")
                except Exception:
                    logger.debug("R4Agent: pmu increment failed, skipped", exc_info=True)
            logger.info("R4Agent: evolved skill '%s' from intent: %.80s", name, intent)
            return {
                "success": True,
                "skill": name,
                "description": skill_def.get("description", ""),
                "rules": len(skill_def.get("rules", [])),
                "scope": scope,
            }

        except json.JSONDecodeError as e:
            logger.warning("R4Agent: evolve_skill JSON parse error: %s", e)
            return {"success": False, "error": f"LLM returned invalid JSON: {e}"}
        except Exception as e:
            logger.warning("R4Agent: evolve_skill failed: %s", e)
            return {"success": False, "error": str(e)}
