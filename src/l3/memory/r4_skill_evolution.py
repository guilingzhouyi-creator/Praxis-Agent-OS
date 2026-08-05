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
    R4_EVOLVED_SKILLS_DEFAULT,
    R4_LEAN_GENERALIZE_THRESHOLD,
    R4_SUMMARIZE_COOLDOWN,
    R4_SUMMARIZE_MAX_TOKENS,
    R4_SUMMARIZE_MIN_INTERVAL,
    R4_SUMMARIZE_MIN_LEN,
    SKILL_ARCHITECT_MAX_TOKENS,
)
from l1.kernel.params.system import (
    HASH_TRUNC_MEDIUM,
    LOG_TRUNC_30,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SKILL_TTL_DAYS,
)

logger = logging.getLogger(__name__)


class SkillEvolutionMixin:
    """SkillEvolutionMixin — skill evolution, persistence and summarization."""

    def _skill_md_path(self, name: str) -> str:
        """Resolve the SKILL.md path for a skill in the evolved dir.

        Layered persistence: project scope → travels with the repo; global
        scope → machine-local data dir (must match the boot discovery dirs).
        """
        import os

        from l1.kernel.paths import get_paths as _gp
        from l3.memory.r4_agent import _resolve_skill_scope
        scope = _resolve_skill_scope()
        evolved_base = (_gp().skill_project_evolved_dir if scope == "project"
                        else _gp().skill_evolved_dir)
        return os.path.join(evolved_base, name, "SKILL.md")

    def _persist_skill_md(self, name: str, description: str, prompt: str,
                          tags: list[str], allowed_tools: list[str] | None = None,
                          rules: list[str] | None = None,
                          procedures: list[dict] | None = None,
                          variables: dict | None = None,
                          disable_model_invocation: bool = False,
                          dependencies: list[str] | None = None,
                          dependency_kind: str = "soft") -> str:
        """Persist a skill as SKILL.md with round-trip frontmatter.

        Frontmatter carries name/description/tags/allowed_tools/variables/
        disable-model-invocation/dependencies/dependency-kind so a reload via
        SkillManager._load_markdown() restores them; the prompt is the body.
        Shared by evolve_skill (LLM) and _generalize_lean_cases (rule-based)
        so both survive restart via the boot discovery dirs.
        """
        import os

        import yaml as _yaml
        md_path = self._skill_md_path(name)
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        meta = {"name": name, "description": description, "tags": tags}
        if disable_model_invocation:
            meta["disable-model-invocation"] = True
        if dependencies:
            meta["dependencies"] = dependencies
        if dependency_kind != "soft":
            meta["dependency-kind"] = dependency_kind
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
            return None
        if now - self._last_summarize_any < R4_SUMMARIZE_MIN_INTERVAL:
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
            result = engine.generate(prompt=prompt,
                                     system="You are a skill architect.",
                                     max_tokens=R4_SUMMARIZE_MAX_TOKENS,
                                     user_id="r4-agent")
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
        except Exception:
            lesson = ""
        lesson = lesson.strip() if isinstance(lesson, str) else ""
        if len(lesson) < R4_SUMMARIZE_MIN_LEN:
            logger.info("R4Agent: summarized lesson for %s rejected (too short)", tool)
            return None
        return lesson

    @staticmethod
    def _archive_before_evolve(name: str, skill_data: dict) -> None:
        """R4 archive: persist a skill version before it is overwritten.

        Records the pre-evolution version under ``fonds="skills"``,
        ``series="evolved"`` as an audit / rollback baseline.  Non-blocking.
        """
        try:
            from l3.tools._archive import _cmd_archive_store
            _cmd_archive_store(
                fonds="skills", series="evolved",
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
            g.add_semantic_edge(from_id=tool, to_id=skill_name,
                                relation="depends_on", created_by="r4-agent")
        except Exception as e:
            logger.debug("R4Agent: lean graph edge skipped: %s", e)

    def _prune_stale_skills(self) -> int:
        """Mark evolved skills that exceed TTL as stale, then delete them.

        Only affects skills tagged ``evolved`` (not ``lean_case`` or built-in).
        A skill is stale if ``last_used`` is 0 and ``loaded_at`` + TTL < now,
        or if ``last_used`` + TTL < now.
        """
        import time as _time

        from l1.kernel.skill import get_skill_manager
        sm = get_skill_manager()
        now = _time.time()
        ttl_seconds = SKILL_TTL_DAYS * SECONDS_PER_DAY
        pruned = 0
        for s in sm.list(tags=["evolved"], sort_by="loaded_at"):
            tags = s.get("tags", [])
            # Skip lean cases and built-in skills
            if "lean_case" in tags or "builtin" in tags:
                continue
            name = s["name"]
            loaded_at = s.get("loaded_at", 0.0)
            last_used = s.get("last_used", 0.0)
            age = now - last_used if last_used > 0 else now - loaded_at
            if age > ttl_seconds:
                # R4 archive before pruning — TTL removal is auditable/restorable.
                try:
                    from l3.tools._archive import _cmd_archive_store
                    _cmd_archive_store(
                        fonds="skills", series="pruned",
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
                        logger.info("R4Agent: cleaned orphan trace %s (age=%.1fh)", fn, (now - mtime) / SECONDS_PER_HOUR)
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
        seeds = [s["name"] for s in sm.list(tags=["evolved"], limit=20)]
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
        for s in sm.list(tags=["lean_case"]):
            tools = s.get("allowed_tools") or []
            tool = tools[0] if tools else (s.get("tags") or [""])[-1]
            if not tool:
                continue
            by_tool.setdefault(tool, []).append(s)

        generalized = 0
        for tool, cases in by_tool.items():
            if len(cases) < R4_LEAN_GENERALIZE_THRESHOLD:
                continue
            gen_name = f"lean_{tool}_lessons"
            lessons = "\n".join(f"- {c.get('prompt', '')[:LOG_TRUNC_200]}" for c in cases)
            baseline = f"Known failure patterns when using {tool}:\n{lessons}"
            # Deterministic case fingerprint — idempotency is independent of
            # whether the stored prompt is LLM-summarized or rule-based, so a
            # refresh during the LLM cooldown never downgrades a refined lesson.
            fp = hashlib.md5(lessons.encode("utf-8")).hexdigest()[:HASH_TRUNC_MEDIUM]
            desc = f"Consolidated failure lessons for {tool} ({len(cases)} cases) [{fp}]"
            existing = sm.get(gen_name)
            if existing and self._fp_of(existing) == fp and os.path.exists(self._skill_md_path(gen_name)):
                continue  # same case set already generalized + persisted
            # P3: LLM semantic summary (gated: threshold + per-tool cooldown +
            # per-tick throttle); any failure degrades to the rule-based baseline.
            llm_lesson = self._summarize_tool_lessons(tool, cases)
            candidate = llm_lesson if llm_lesson else baseline
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

    def evolve_skill(self, intent: str, cell_id: str = "") -> dict:
        """Use LLM to generate a new skill definition from a natural language intent.

        Uses the LLM engine to produce a structured skill (name, description, rules,
        procedures, system prompt), then registers it with SkillManager and persists
        it as a SKILL.md file in the evolved skills directory.

        When ``cell_id`` is provided, the evolved skill is also bound to that
        Cell's white-list (演化即回灌) so its agents can inject it immediately.

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
            result = engine.generate(prompt=prompt, system=system, max_tokens=SKILL_ARCHITECT_MAX_TOKENS,
                                     user_id="r4-agent", **model_kwargs)

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
            skill_desc = skill_def.get("description")
            skill_desc = skill_desc if isinstance(skill_desc, str) else ""
            skill_prompt = skill_def.get("prompt")
            skill_prompt = skill_prompt if isinstance(skill_prompt, str) else ""
            skill_rules = [r for r in (skill_def.get("rules") or []) if isinstance(r, str)]
            skill_procs = [p for p in (skill_def.get("procedures") or []) if isinstance(p, dict)]
            skill_tools = skill_def.get("allowed_tools")
            if not isinstance(skill_tools, list) or not all(isinstance(t, str) for t in skill_tools):
                skill_tools = None
            sm.create(
                name=name,
                description=skill_desc,
                prompt=skill_prompt,
                tags=skill_tags,
                rules=skill_rules,
                procedures=skill_procs,
                allowed_tools=skill_tools,
                internal=True,
            )
            if existing:
                # Preserve usage counters across the overwrite — a re-evolve
                # must not reset usefulness tracking (TTL/quality signals).
                try:
                    sm.update(name, {
                        "useful_count": existing.get("useful_count", 0) or 0,
                        "last_used": existing.get("last_used", 0.0) or 0.0,
                    })
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
                    g.add_semantic_edge(from_id=backup_name, to_id=name,
                                        relation="refines", created_by="r4-agent")
                g.remember_hook(entry_id=name, agent_id=self.agent_id,
                                entry_type="skill", cell_id=cell_id,
                                recent=[{"id": backup_name, "entry_type": "skill",
                                         "agent_id": self.agent_id, "cell_id": cell_id}]
                                if existing else [],
                                created_by="r4-agent")
            except Exception as e:
                logger.debug("R4Agent: skill graph linkage skipped: %s", e)

            # Persist as SKILL.md — shared helper keeps round-trip frontmatter
            # (tags/allowed_tools/variables survive reload) for both the LLM
            # evolve path and the rule-based generalization path.
            from l3.memory.r4_agent import _resolve_skill_scope
            scope = _resolve_skill_scope()
            self._persist_skill_md(
                name=name, description=skill_desc, prompt=skill_prompt,
                tags=skill_tags, allowed_tools=skill_tools,
                rules=skill_rules, procedures=skill_procs,
                variables=skill_def.get("variables"),
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
