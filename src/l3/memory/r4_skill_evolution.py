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
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import (
    R4_CARD_TAG_MAX,
    R4_CLUSTER_SAMPLE_MAX,
    R4_CLUSTER_SIMILARITY,
    R4_CONTRIB_MIN_RATIO,
    R4_CONTRIB_MIN_TRIALS,
    R4_CURATION_ENABLED,
    R4_DIFFICULTY_WORDS,
    R4_DISTILL_COOLDOWN,
    R4_DISTILL_SAMPLES,
    R4_EVOLVED_SKILLS_DEFAULT,
    R4_LEAN_GENERALIZE_THRESHOLD,
    R4_RULE_MIN_PREFERRED,
    R4_SUMMARIZE_COOLDOWN,
    R4_SUMMARIZE_MAX_TOKENS,
    R4_SUMMARIZE_MIN_INTERVAL,
    R4_SUMMARIZE_MIN_LEN,
    SKILL_ARCHITECT_MAX_TOKENS,
)
from l1.kernel.params.system import (
    HASH_TRUNC_MEDIUM,
    LOG_TRUNC_80,
    LOG_TRUNC_200,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SKILL_LIBRARY_MAX,
    SKILL_POSTURE_DEFAULT,
    SKILL_POSTURE_VALID,
    SKILL_TTL_DAYS,
    SKILL_TTL_EXTEND_PER_USE,
)

logger = logging.getLogger(__name__)


def _scrub_skill_prompt(prompt: str, violations: list[str]) -> str:
    """Drop lines from a prompt that carry contract violations.

    Line-level scrub: removes any line matching a forbidden constitutional
    pattern or containing a project-specific literal, so the surviving body
    stays usable. Returns the scrubbed prompt (may be empty → caller
    rejects).
    """
    import re as _re

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


class SkillEvolutionMixin:
    """SkillEvolutionMixin — skill evolution, persistence and summarization."""

    # ── Attributes injected by the concrete R4Agent (see r4_agent.py) ──
    agent_id: str
    _last_summarize: dict[str, float]
    _last_summarize_any: float
    _last_distill: dict[str, float]
    _pmu: Any

    def reflect_failure(self, tool: str, cases: list[dict]) -> str | None:
        """Reflexion-style attribution (provided by SkillFeedbackMixin)."""
        raise NotImplementedError

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

    def _summarize_tool_lessons(self, tool: str, cases: list[dict]) -> str | None:
        """LLM-summarize a tool's lean cases into one concise lesson.

        Three gates: per-tool cooldown (R4_SUMMARIZE_COOLDOWN), global throttle
        (R4_SUMMARIZE_MIN_INTERVAL), and the caller's threshold check.  Any
        failure (LLM error, invalid JSON, below the length floor) returns None
        so the caller falls back to the rule-based baseline.  Never writes —
        the caller owns the write.
        """
        import json as _json

        now = time.time()
        if now - self._last_summarize.get(tool, 0.0) < R4_SUMMARIZE_COOLDOWN:
            logger.debug("R4Agent: lesson summarization for %s skipped (cooldown)", tool)
            return None
        if now - self._last_summarize_any < R4_SUMMARIZE_MIN_INTERVAL:
            logger.debug("R4Agent: lesson summarization skipped (global throttle)")
            return None
        digest = "\n".join(f"- {c.get('prompt', '')[:LOG_TRUNC_200]}" for c in cases)
        prompt = (
            "Distill these failure patterns for the tool into ONE concise "
            f"reusable lesson.\n{digest}\n"
            'Reply with JSON only: {"lesson": "<one paragraph>"}'
        )
        try:
            from l4.llm.llm import get_engine

            engine = get_engine()
            result = engine.generate(
                prompt=prompt,
                system="You are a skill architect.",
                max_tokens=R4_SUMMARIZE_MAX_TOKENS,
                user_id="r4-agent",
            )
        except Exception as e:
            logger.warning("R4Agent: lesson summarization failed: %s", e)
            self._last_summarize[tool] = now
            return None
        self._last_summarize[tool] = now
        self._last_summarize_any = now
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
            lesson = data.get("lesson", "") if isinstance(data, dict) else ""
        except Exception as e:
            logger.warning("R4Agent: lesson summarization returned invalid JSON for %s: %s", tool, e)
            lesson = ""
        lesson = lesson.strip() if isinstance(lesson, str) else ""
        if len(lesson) < R4_SUMMARIZE_MIN_LEN:
            logger.info("R4Agent: summarized lesson for %s rejected (too short)", tool)
            return None
        return lesson

    def _distill_lessons_skill(self, tool: str, cases: list[dict], verified_context: str = "") -> dict | None:
        """Distill a tool's lean cases into a structured skill definition.

        Batch 3 upgrade: rejection sampling. Up to ``R4_DISTILL_SAMPLES``
        (1-3, configurable) candidate definitions are sampled for the same
        digest; a heuristic verifier scores each (operability, coverage of
        the digest's error terms, consistency) and the best-scoring
        candidate wins. Any failure degrades to None so the caller keeps
        the summary fallback. ``verified_context`` (batch 2) carries
        already-verified rules across re-distillation.
        """
        now = time.time()
        if now - self._last_distill.get(tool, 0.0) < R4_DISTILL_COOLDOWN:
            logger.debug("R4Agent: skill distillation for %s skipped (cooldown)", tool)
            return None
        digest = "\n".join(f"- {c.get('prompt', '')[:LOG_TRUNC_200]}" for c in cases)
        samples = int(R4_DISTILL_SAMPLES) if R4_DISTILL_SAMPLES >= 1 else 1
        best: dict | None = None
        best_score = -1.0
        for _i in range(samples):
            candidate = self._sample_distill_candidate(tool, digest, verified_context)
            if candidate is None:
                continue
            score = self._score_distill_candidate(candidate, digest)
            if score > best_score:
                best, best_score = candidate, score
        if best is not None:
            self._last_distill[tool] = now
        return best

    def _sample_distill_candidate(self, tool: str, digest: str, verified_context: str) -> dict | None:
        """One LLM sample of a distilled skill definition (batch 3)."""
        import json as _json

        from l1.kernel.skill import validate_skill_content as _validate_content

        prompt = (
            "You are a skill architect. Distill these failure patterns for "
            f"the tool '{tool}' into a structured skill definition:\n{digest}\n"
            f"{verified_context}\n"
            'Reply with JSON only: {"name": "<tool>_lessons", '
            '"description": "<one line>", "prompt": "<procedural guidance>", '
            '"rules": ["DO: ...", "DONT: ..."], "procedures": [{"step": "..."}]}'
        )
        try:
            from l4.llm.llm import get_engine

            engine = get_engine()
            result = engine.generate(
                prompt=prompt,
                system="You are a skill architect.",
                max_tokens=R4_SUMMARIZE_MAX_TOKENS,
                user_id="r4-agent",
            )
        except Exception as e:
            logger.warning("R4Agent: skill distillation failed: %s", e)
            return None
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
        except Exception as e:
            logger.warning("R4Agent: distillation invalid JSON for %s: %s", tool, e)
            return None
        if not isinstance(data, dict):
            return None
        skill_prompt = data.get("prompt") if isinstance(data.get("prompt"), str) else ""
        skill_desc = data.get("description") if isinstance(data.get("description"), str) else ""
        if len(skill_prompt or "") < R4_SUMMARIZE_MIN_LEN:
            logger.info("R4Agent: distilled skill for %s rejected (too short)", tool)
            return None
        if _validate_content(skill_prompt, skill_desc):
            logger.warning("R4Agent: distilled skill for %s violates content contract — dropped", tool)
            return None
        # Batch 2: rules carry DPO-style preference metadata so downstream
        # card signals can weight them (verified/hit/preferred/deprecated).
        rules = []
        for r in (data.get("rules") or []):
            if isinstance(r, str):
                rules.append({"rule": r, "verified": 0, "hit": 0, "preferred": 1.0, "deprecated": False})
            elif isinstance(r, dict) and r.get("rule"):
                rules.append(
                    {
                        "rule": str(r.get("rule")),
                        "verified": int(r.get("verified", 0) or 0),
                        "hit": int(r.get("hit", 0) or 0),
                        "preferred": float(r.get("preferred", 1.0) or 1.0),
                        "deprecated": bool(r.get("deprecated", False)),
                    }
                )
        procs = [p for p in (data.get("procedures") or []) if isinstance(p, dict)]
        return {"prompt": skill_prompt, "rules": rules, "procedures": procs}

    def _score_distill_candidate(self, candidate: dict, digest: str) -> float:
        """Heuristic verifier for a distilled candidate (batch 3).

        Three signals, summed:
          - operability: share of rules that are actionable (start with
            DO/DONT/CHECK/VERIFY/ALWAYS/NEVER) — rewards enforceable rules
          - coverage: share of the digest's distinct error terms mentioned
            across the candidate's prompt+rules — rewards completeness
          - structure: procedures present add a bonus (structured skills
            are more executable than prose-only ones)
        Returns a score in [0, 3].
        """
        import re as _re

        rules = candidate.get("rules") or []
        rule_texts = [r.get("rule", "") if isinstance(r, dict) else str(r) for r in rules]
        prompt = candidate.get("prompt", "") or ""
        # Operability.
        actionable = 0
        for rt in rule_texts:
            head = rt.strip().upper()
            if any(head.startswith(p) for p in ("DO", "DON'T", "DONT", "CHECK", "VERIFY", "ALWAYS", "NEVER")):
                actionable += 1
        operability = actionable / len(rule_texts) if rule_texts else 0.0
        # Coverage: digest error terms appearing in prompt+rules.
        terms = set(_re.split(r"[\s,;:._-]+", digest.lower()))
        terms = {t for t in terms if len(t) > 2}
        blob = f"{prompt} {' '.join(rule_texts)}".lower()
        covered = sum(1 for t in terms if t in blob)
        coverage = covered / len(terms) if terms else 0.0
        # Structure bonus.
        structure = 1.0 if candidate.get("procedures") else 0.0
        return round(operability + coverage + structure, 3)

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

    def _prune_stale_skills(self) -> int:
        """Mark evolved skills that exceed TTL as stale, then delete them.

        Only affects skills tagged ``evolved`` (not ``lean_case`` or built-in).
        A skill is stale if ``last_used`` is 0 and ``loaded_at`` + TTL < now,
        or if ``last_used`` + TTL < now.  Each recorded use (``useful_count``)
        extends the effective TTL by ``SKILL_TTL_EXTEND_PER_USE`` seconds —
        reused skills live longer, unused ones expire sooner.
        """
        import time as _time

        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        now = _time.time()
        ttl_seconds = SKILL_TTL_DAYS * SECONDS_PER_DAY
        pruned = 0
        for s in sm.list_skills(tags=["evolved"], sort_by="loaded_at"):
            tags = s.get("tags", [])
            # Skip lean cases and built-in skills
            if "lean_case" in tags or "builtin" in tags:
                continue
            name = s["name"]
            loaded_at = s.get("loaded_at", 0.0)
            last_used = s.get("last_used", 0.0)
            useful = s.get("useful_count", 0) or 0
            age = now - last_used if last_used > 0 else now - loaded_at
            effective_ttl = ttl_seconds + useful * SKILL_TTL_EXTEND_PER_USE
            if age > effective_ttl:
                # R4 archive before pruning — TTL removal is auditable/restorable.
                try:
                    from l3.tools._archive import _cmd_archive_store

                    _cmd_archive_store(
                        fonds="skills",
                        series="pruned",
                        content=s.get("prompt", "") or "",
                        tags=f"{name},evolved,pruned",
                    )
                except Exception as e:
                    logger.debug("R4Agent: archive pruned skill failed: %s", e)
                sm.delete(name, internal=True)
                # Also remove the persisted SKILL.md (project + global scope)
                # so the prune survives reload — otherwise _load_markdown
                # resurrects the skill with a fresh loaded_at and the TTL
                # clock restarts. The R4 archive above keeps the audit trail.
                try:
                    import os
                    import shutil

                    from l1.kernel.paths import get_paths as _gp_paths

                    _p = _gp_paths()
                    for base in (_p.skill_project_evolved_dir, _p.skill_evolved_dir):
                        skill_dir = os.path.join(base, name)
                        if os.path.isdir(skill_dir):
                            shutil.rmtree(skill_dir, ignore_errors=True)
                except Exception as e:
                    logger.debug("R4Agent: pruned skill dir cleanup failed: %s", e)
                pruned += 1
                logger.info("R4Agent: pruned stale skill '%s' (age=%.1f days)", name, age / SECONDS_PER_DAY)
        return pruned

    def record_card_skill_signal(self, skills_used: list[str], success: bool) -> int:
        """DPO-style preference signal: adjust rule weights from card outcome.

        For each skill used during a card, attribute the card's
        success/failure to its generalized lessons rules:
          - success → ``verified++``, ``preferred`` up (REP_TASK_SUCCESS delta)
          - failure → ``hit++``, ``preferred`` down (REP_TASK_FAILURE delta)
        Rules whose ``preferred`` drops below ``R4_RULE_MIN_PREFERRED`` are
        marked ``deprecated`` — the next targeted re-distill rewrites them.
        Returns the number of rules updated (0 when no signal applies).
        """
        from l1.kernel.params.agent import REP_TASK_FAILURE, REP_TASK_SUCCESS
        from l1.kernel.skill import get_skill_manager

        if not skills_used:
            return 0
        try:
            sm = get_skill_manager()
        except Exception:
            return 0
        delta = REP_TASK_SUCCESS if success else REP_TASK_FAILURE
        updated = 0
        for name in skills_used:
            # Only generalized lessons skills carry weighted rules.
            rec = sm.get(name)
            if not rec:
                continue
            rules = rec.get("rules") or []
            if not isinstance(rules, list):
                continue
            new_rules: list[Any] = []
            changed = False
            for r in rules:
                if isinstance(r, str):
                    new_rules.append(r)
                    continue
                if not isinstance(r, dict):
                    continue
                meta = dict(r)
                rule_text = meta.get("rule", "")
                if not rule_text:
                    continue
                preferred = float(meta.get("preferred", 1.0)) + delta
                meta["preferred"] = round(max(0.0, min(1.0, preferred)), 3)
                if success:
                    meta["verified"] = int(meta.get("verified", 0)) + 1
                else:
                    meta["hit"] = int(meta.get("hit", 0)) + 1
                if meta["preferred"] < R4_RULE_MIN_PREFERRED:
                    meta["deprecated"] = True
                new_rules.append(meta)
                changed = True
            if changed:
                try:
                    sm.update(name, {"rules": new_rules}, internal=True)
                    updated += 1
                except Exception:
                    logger.debug("R4Agent: rule preference update failed for %s", name)
        return updated

    def _detect_skill_conflicts(self) -> list[dict]:
        """Detect duplicate / contradictory evolved skills per tool.

        Consistency pass over evolved skills (excludes built-in and
        lean_case): for each tool group (by ``allowed_tools``), pairs whose
        prompt token-set Jaccard similarity exceeds
        ``SKILL_CONFLICT_SIMILARITY`` are flagged as duplicates; rules that
        directly contradict (a DO: X vs a DON'T: X on the same topic) are
        flagged as conflicts. Returns a report list; the caller decides how
        to surface it (tick results / alert). Read-only — never mutates.
        """
        import re as _re

        from l1.kernel.params.system import (
            SKILL_CONFLICT_SCAN_LIMIT,
            SKILL_CONFLICT_SIMILARITY,
        )

        try:
            from l1.kernel.skill import get_skill_manager
        except Exception:
            return []
        sm = get_skill_manager()
        # list_skills returns summary dicts (rules = count); fetch full
        # records for rule-level analysis.
        skills = [
            sm.get(s["name"]) for s in sm.list_skills(tags=["evolved"], limit=SKILL_CONFLICT_SCAN_LIMIT)
            if sm.get(s["name"])
        ]
        skills = [
            s for s in skills
            if "lean_case" not in (s.get("tags") or []) and "builtin" not in (s.get("tags") or [])
        ]
        by_tool: dict[str, list[dict]] = {}
        for s in skills:
            tools = s.get("allowed_tools") or []
            tool = tools[0] if tools else "general"
            by_tool.setdefault(tool, []).append(s)

        def _tokens(text: str) -> set[str]:
            return set(_re.split(r"[\s,;:._-]+", (text or "").lower()))

        report: list[dict] = []
        for tool, group in by_tool.items():
            if len(group) < 2:
                continue
            tok_cache = {s["name"]: _tokens(s.get("prompt", "")) for s in group}
            for i, a in enumerate(group):
                for b in group[i + 1 :]:
                    ta, tb = tok_cache[a["name"]], tok_cache[b["name"]]
                    if not ta or not tb:
                        continue
                    inter = len(ta & tb)
                    union = len(ta | tb)
                    if union and inter / union >= SKILL_CONFLICT_SIMILARITY:
                        report.append(
                            {
                                "kind": "duplicate",
                                "tool": tool,
                                "skills": [a["name"], b["name"]],
                                "similarity": round(inter / union, 2),
                            }
                        )
                    # Rule contradiction: DO: X in one, DON'T: X in the other.
                    # Rules may be str (legacy) or dict with preference
                    # metadata (batch 2) — normalize both to text.
                    ra_raw, rb_raw = a.get("rules"), b.get("rules")
                    ra_list = ra_raw if isinstance(ra_raw, list) else []
                    rb_list = rb_raw if isinstance(rb_raw, list) else []

                    def _rule_text(r: Any) -> str:
                        return r.get("rule", "") if isinstance(r, dict) else (r if isinstance(r, str) else "")

                    rules_a = [_rule_text(r).lower() for r in ra_list if _rule_text(r)]
                    rules_b = [_rule_text(r).lower() for r in rb_list if _rule_text(r)]
                    for ra in rules_a:
                        for rb in rules_b:
                            topic = _re.sub(r"^(do|don'?t)\s*[:.]?\s*", "", ra)
                            if not topic:
                                continue
                            neg_b = rb.startswith(("don't", "dont", "do not"))
                            neg_a = ra.startswith(("don't", "dont", "do not"))
                            if neg_a != neg_b and topic in rb:
                                report.append(
                                    {
                                        "kind": "contradiction",
                                        "tool": tool,
                                        "skills": [a["name"], b["name"]],
                                        "rule_a": ra[:LOG_TRUNC_80],
                                        "rule_b": rb[:LOG_TRUNC_80],
                                    }
                                )
        return report

    def _curate_skills(self) -> int:
        """Evaluate evolved skills by contribution and enforce the library cap.

        Contribution ``c(s) = useful_count / max(injected_count, 1)`` measures
        how often an injected skill actually proved useful.  Skills with at
        least ``R4_CONTRIB_MIN_TRIALS`` injections and ``c(s) <
        R4_CONTRIB_MIN_RATIO`` are retired (archived, then deleted).  When
        the evolved library exceeds ``SKILL_LIBRARY_MAX``, the lowest-
        contribution skills are evicted until under the cap.  Gated by
        ``R4_CURATION_ENABLED``; never touches built-in or lean-case skills.
        """

        from l1.kernel.skill import get_skill_manager

        if not R4_CURATION_ENABLED:
            return 0
        sm = get_skill_manager()
        evolved: list[dict] = []
        for s in sm.list_skills(tags=["evolved"], sort_by="loaded_at"):
            tags = s.get("tags", [])
            if "lean_case" in tags or "builtin" in tags:
                continue
            useful = s.get("useful_count", 0) or 0
            injected = s.get("inject_count", 0) or 0
            contrib = useful / max(injected, 1)
            evolved.append(
                {
                    "name": s["name"],
                    "useful": useful,
                    "injected": injected,
                    "contrib": contrib,
                    "record": s,
                }
            )

        retired = 0
        # 1. Retire under-performers with enough trials.
        for e in evolved:
            if e["injected"] >= R4_CONTRIB_MIN_TRIALS and e["contrib"] < R4_CONTRIB_MIN_RATIO:
                try:
                    from l3.tools._archive import _cmd_archive_store

                    _cmd_archive_store(
                        fonds="skills",
                        series="retired",
                        content=e["record"].get("prompt", "") or "",
                        tags=f"{e['name']},evolved,retired,contrib={e['contrib']:.2f}",
                    )
                except Exception as ex:
                    logger.debug("R4Agent: archive retired skill failed: %s", ex)
                sm.delete(e["name"], internal=True)
                self._remove_skill_dir(e["name"])
                logger.info(
                    "R4Agent: retired under-performing skill '%s' (contrib=%.2f, trials=%d)",
                    e["name"],
                    e["contrib"],
                    e["injected"],
                )
                retired += 1
        if retired:
            evolved = [e for e in evolved if e["name"] not in set()]  # noqa — filtered below via re-list
            evolved = [e for e in evolved if sm.get(e["name"]) is not None]

        # 2. Enforce the library cap: evict lowest contribution.
        evicted = 0
        while len(evolved) > SKILL_LIBRARY_MAX:
            worst = min(evolved, key=lambda e: e["contrib"])
            try:
                from l3.tools._archive import _cmd_archive_store

                _cmd_archive_store(
                    fonds="skills",
                    series="evicted",
                    content=worst["record"].get("prompt", "") or "",
                    tags=f"{worst['name']},evolved,evicted,contrib={worst['contrib']:.2f}",
                )
            except Exception as ex:
                logger.debug("R4Agent: archive evicted skill failed: %s", ex)
            sm.delete(worst["name"], internal=True)
            self._remove_skill_dir(worst["name"])
            logger.info(
                "R4Agent: evicted lowest-contribution skill '%s' (contrib=%.2f) — cap %d",
                worst["name"],
                worst["contrib"],
                SKILL_LIBRARY_MAX,
            )
            evolved.remove(worst)
            evicted += 1
        if self._pmu:
            try:
                self._pmu.increment("skills.curated.retired", retired)
                self._pmu.increment("skills.curated.evicted", evicted)
            except Exception:
                logger.debug("R4Agent: pmu increment failed, skipped", exc_info=True)
        return retired + evicted

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

    def _clean_orphan_traces(self) -> int:
        """Remove unresolvable failure trace files older than 24 hours.

        If ``_process_failure_traces`` failed to process a trace (e.g. R4
        was not running), the JSON file stays on disk indefinitely.  This
        method deletes files older than 24 hours that are still marked
        ``resolved: false``.
        """
        import json
        import os

        from l1.kernel.paths import get_paths as _gp

        lean_dir = _gp().skill_lean_dir
        if not os.path.isdir(lean_dir):
            return 0
        now = time.time()
        max_age = SECONDS_PER_DAY  # 24 hours
        cleaned = 0
        for fn in os.listdir(lean_dir):
            if not fn.endswith(".json"):
                continue
            fp = os.path.join(lean_dir, fn)
            try:
                mtime = os.path.getmtime(fp)
                if now - mtime > max_age:
                    with open(fp, encoding="utf-8") as f:
                        entry = json.load(f)
                    if not entry.get("resolved", False):
                        os.remove(fp)
                        cleaned += 1
                        logger.info(
                            "R4Agent: cleaned orphan trace %s (age=%.1fh)", fn, (now - mtime) / SECONDS_PER_HOUR
                        )
            except Exception as e:
                logger.debug("R4Agent: orphan check %s skipped: %s", fn, e)
        return cleaned

    def _graph_diffuse_evolved(self, limit: int = R4_EVOLVED_SKILLS_DEFAULT) -> list[str]:
        """Diffuse-recall evolved skills along R5 graph edges.

        Seeds with the current evolved skill names, BFS one hop via
        memory_graph.recall() and returns skill names reached.  Empty when the
        graph is disabled or no edges exist — caller falls back to linear.
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        seeds = [s["name"] for s in sm.list_skills(tags=["evolved"], limit=20)]
        if not seeds:
            return []
        try:
            from l3.memory.memory_graph import get_graph as _get_graph

            g = _get_graph()
            r = g.recall(seeds=seeds, depth=1, limit=limit * 4)
        except Exception as e:
            logger.debug("R4Agent: graph diffusion unavailable: %s", e)
            return []
        nodes = r.get("nodes", []) if isinstance(r, dict) else []
        # Nodes include the seeds themselves (BFS start); return neighbors only,
        # preserving the seed-first order that recall already emits.
        return [n for n in nodes if n not in seeds][:limit]

    def _cluster_lean_cases(self, cases: list[dict]) -> list[list[dict]]:
        """Semantic clustering of lean cases by error text (batch 4).

        Uses 3-gram shingle Jaccard similarity on the case's error text
        (from structured knowledge when present, else the prompt). Cases
        whose shingle similarity exceeds ``R4_CLUSTER_SIMILARITY`` are
        merged into one cluster — same-root-cause failures written
        differently no longer split across distillations.
        """
        import re as _re

        def _error_text(c: dict) -> str:
            kn = c.get("knowledge") or {}
            err = kn.get("error", "") if isinstance(kn, dict) else ""
            if not err:
                err = c.get("prompt", "") or ""
            return err.lower()

        def _shingles(text: str) -> set[str]:
            words = _re.split(r"[\s,;:._\-/]+", text)
            words = [w for w in words if len(w) > 2]
            return {f"{words[i]}_{words[i+1]}_{words[i+2]}" for i in range(len(words) - 2)}

        cache = {id(c): _shingles(_error_text(c)) for c in cases}
        clusters: list[list[dict]] = []
        for c in cases:
            c_sh = cache[id(c)]
            placed = False
            for cl in clusters:
                rep_sh = cache[id(cl[0])]
                union = c_sh | rep_sh
                if union and len(c_sh & rep_sh) / len(union) >= R4_CLUSTER_SIMILARITY:
                    cl.append(c)
                    placed = True
                    break
            if not placed:
                clusters.append([c])
        return clusters

    def _sample_digest(self, cases: list[dict], tool: str) -> str:
        """Build a distillation digest with frequency weighting + difficulty order.

        Batch 4 curriculum-style sampling: clusters are ordered by size
        (frequent failure modes first), each cluster contributes up to
        ``R4_CLUSTER_SAMPLE_MAX`` representative cases, and within a cluster
        simpler patterns (short error text) come before complex ones (long
        error text, ``R4_DIFFICULTY_WORDS``+ words).
        """
        clusters = self._cluster_lean_cases(cases)
        clusters.sort(key=len, reverse=True)
        lines: list[str] = []
        for cl in clusters:
            # Representative sampling within the cluster: shortest (simplest)
            # first, then progressively longer (difficulty ramp). Complex
            # patterns (>= R4_DIFFICULTY_WORDS words in the error text) get a
            # marker so the LLM treats them as edge cases, not the norm.
            def _err_len(c: dict) -> int:
                kn = c.get("knowledge") or {}
                if isinstance(kn, dict) and kn.get("error"):
                    return len(str(kn["error"]).split())
                return len((c.get("prompt") or "").split())

            sub = sorted(cl, key=_err_len)
            for c in sub[:R4_CLUSTER_SAMPLE_MAX]:
                kn = c.get("knowledge") or {}
                if isinstance(kn, dict) and kn.get("error"):
                    marker = "[complex]" if _err_len(c) >= R4_DIFFICULTY_WORDS else ""
                    lines.append(f"- {marker}{tool}: {kn['error'][:LOG_TRUNC_200]}")
                else:
                    lines.append(f"- {c.get('prompt', '')[:LOG_TRUNC_200]}")
        return "\n".join(lines) if lines else "\n".join(f"- {c.get('prompt', '')[:LOG_TRUNC_200]}" for c in cases)

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
                        verified_context = (
                            "\nAlready-verified rules to KEEP (do not contradict):\n"
                            + "\n".join(f"- {r}" for r in keep)
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

    def evolve_skill(self, intent: str, cell_id: str = "", scope: str = "",
                     extra_tags: list[str] | None = None) -> dict:
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
                skill_tags += [t for t in extra_tags if isinstance(t, str) and t not in skill_tags][
                    :R4_CARD_TAG_MAX
                ]
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

            violations = _validate_content(skill_prompt, skill_desc)
            if violations:
                logger.warning(
                    "R4Agent: evolved skill '%s' violates content contract, scrubbing: %s",
                    name, "; ".join(violations),
                )
                skill_prompt = _scrub_skill_prompt(skill_prompt, violations)
                skill_desc = skill_desc if _validate_content(skill_prompt, skill_desc) == [] else ""
                if not skill_prompt.strip():
                    return {"success": False, "error": f"skill '{name}' rejected: content contract violations: {violations}"}
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
