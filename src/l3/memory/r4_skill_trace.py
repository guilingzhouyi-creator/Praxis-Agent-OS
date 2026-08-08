"""SkillTraceMixin — failure-trace intake and reflexion attribution.

Extracted from r4_skill_feedback.py (SkillFeedbackMixin): the failure-trace
pipeline (_track_failure / track_tool_failure / _process_failure_traces)
and the LLM reflexion attribution (reflect_failure). Composed by
SkillFeedbackMixin.
"""

from __future__ import annotations

import logging
import time

from l1.kernel.params.agent import (
    R4_CARD_TAG_PREFIX,
    R4_LEAN_KNOWLEDGE_MAX,
    R4_REFLECTION_COOLDOWN,
    R4_REFLECTION_ENABLED,
    R4_REFLECTION_MAX_TOKENS,
    R4_REFLECTION_MIN_LEN,
)
from l1.kernel.params.system import (
    LOG_TRUNC_30,
    LOG_TRUNC_40,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
)

logger = logging.getLogger(__name__)


class SkillTraceMixin:
    """Failure-trace recording, lean-case generation, and reflexion."""

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
        self,
        agent_id: str,
        tool_name: str,
        args: dict,
        error: str,
        turn_log: list[dict],
        domain: str = "",
        nature: str = "",
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
                    # Structured knowledge: preserve the raw failure detail
                    # (args/error/domain/nature/turn count) so distillation
                    # and summarization see real failure data, not the
                    # flattened prompt template. Truncated to bound memory.
                    try:
                        _knowledge = {
                            "tool": tool,
                            "args": str(entry.get("args", ""))[:R4_LEAN_KNOWLEDGE_MAX],
                            "error": str(entry.get("error", ""))[:R4_LEAN_KNOWLEDGE_MAX],
                            "domain": _domain,
                            "nature": _nature,
                            "turn_count": int(entry.get("turn_count", 0) or 0),
                            "pattern_hint": error_stem,
                        }
                    except Exception:
                        _knowledge = {"tool": tool, "error": error_stem}
                    sm.create(
                        name=skill_name,
                        description=f"Failure case: {tool} — {entry['error'][:LOG_TRUNC_60]}",
                        prompt=lean_text,
                        knowledge=_knowledge,
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
