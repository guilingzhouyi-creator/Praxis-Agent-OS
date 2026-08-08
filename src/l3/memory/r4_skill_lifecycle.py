"""SkillLifecycleMixin — TTL pruning, conflict detection, and curation.

Extracted from r4_skill_evolution.py (SkillEvolutionMixin): stale-skill TTL
pruning, orphan-trace cleanup, R5 graph diffusion recall, duplicate /
contradiction detection, and contribution-based library curation. Composed
by SkillEvolutionMixin.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import (
    R4_CONTRIB_MIN_RATIO,
    R4_CONTRIB_MIN_TRIALS,
    R4_CURATION_ENABLED,
    R4_EVOLVED_SKILLS_DEFAULT,
    REP_TASK_FAILURE,
    REP_TASK_SUCCESS,
)
from l1.kernel.params.system import (
    LOG_TRUNC_80,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SKILL_LIBRARY_MAX,
    SKILL_TTL_DAYS,
    SKILL_TTL_EXTEND_PER_USE,
)

logger = logging.getLogger(__name__)


class SkillLifecycleMixin:
    """TTL pruning, conflict detection, and library curation for evolved skills."""

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
        try:
            from l1.kernel.skill import get_skill_manager as _sm_gate

            if not _sm_gate().distill_policy().get("dpo_signal", True):
                return 0  # DPO signal weighting disabled at runtime
        except Exception:
            pass
        from l1.kernel.params.agent import R4_RULE_MIN_PREFERRED
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
            sm.get(s["name"])
            for s in sm.list_skills(tags=["evolved"], limit=SKILL_CONFLICT_SCAN_LIMIT)
            if sm.get(s["name"])
        ]
        skills = [
            s for s in skills if "lean_case" not in (s.get("tags") or []) and "builtin" not in (s.get("tags") or [])
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

        policy = {}
        try:
            policy = get_skill_manager().pipeline_policy()
        except Exception as e:
            logger.debug("R4Agent: pipeline policy unavailable, using params: %s", e)
        if not bool(policy.get("curation", R4_CURATION_ENABLED)):
            return 0
        sm = get_skill_manager()
        min_trials = int(policy.get("contrib_min_trials", R4_CONTRIB_MIN_TRIALS))
        min_ratio = float(policy.get("contrib_min_ratio", R4_CONTRIB_MIN_RATIO))
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
            if e["injected"] >= min_trials and e["contrib"] < min_ratio:
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
            evolved = [e for e in evolved if sm.get(e["name"]) is not None]

        # 2. Enforce the library cap — evict lowest contribution first.
        if len(evolved) > SKILL_LIBRARY_MAX:
            overflow = sorted(evolved, key=lambda e: e["contrib"])[: len(evolved) - SKILL_LIBRARY_MAX]
            for worst in overflow:
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
                    "R4Agent: evicted low-contribution skill '%s' (contrib=%.2f) — cap %d",
                    worst["name"],
                    worst["contrib"],
                    SKILL_LIBRARY_MAX,
                )
        if self._pmu:
            try:
                self._pmu.increment("skills.curated.retired", retired)
                self._pmu.increment("skills.curated.evicted", len(overflow))
            except Exception:
                logger.debug("R4Agent: pmu increment failed, skipped", exc_info=True)
        return retired + len(overflow)

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
