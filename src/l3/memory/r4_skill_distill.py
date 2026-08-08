"""SkillDistillMixin — LLM lesson summarization and skill distillation.

Extracted from r4_skill_evolution.py (SkillEvolutionMixin): the LLM
summarization pipeline (_summarize_tool_lessons), rejection-sampling
distillation (_distill_lessons_skill / _sample_distill_candidate /
_score_distill_candidate), and the curriculum-style digest builder
(_cluster_lean_cases / _sample_digest). Composed by SkillEvolutionMixin.
"""

from __future__ import annotations

import logging
import time

from l1.kernel.params.agent import (
    R4_CLUSTER_SAMPLE_MAX,
    R4_CLUSTER_SIMILARITY,
    R4_DIFFICULTY_WORDS,
    R4_DISTILL_COOLDOWN,
    R4_DISTILL_SAMPLES,
    R4_SUMMARIZE_COOLDOWN,
    R4_SUMMARIZE_MAX_TOKENS,
    R4_SUMMARIZE_MIN_INTERVAL,
    R4_SUMMARIZE_MIN_LEN,
)
from l1.kernel.params.system import LOG_TRUNC_200

logger = logging.getLogger(__name__)


class SkillDistillMixin:
    """LLM lesson summarization, rejection-sampling distillation, and digests."""

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
        # Degradation: llm_distill sub-switch OFF → no LLM calls at all; the
        # caller falls back to the rule baseline (cheapest mode).
        try:
            from l1.kernel.skill import get_skill_manager as _sm_gate

            if not _sm_gate().distill_policy().get("sub", {}).get("llm_distill", True):
                return None
        except Exception:
            pass
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
        for r in data.get("rules") or []:
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
            return {f"{words[i]}_{words[i + 1]}_{words[i + 2]}" for i in range(len(words) - 2)}

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
        # Degradation chain: clustering OFF → plain by-tool grouping (each
        # case its own cluster); sampling OFF → flat digest of all cases.
        try:
            from l1.kernel.skill import get_skill_manager as _sm_gate

            _sub = _sm_gate().distill_policy().get("sub", {})
            _clustering = _sub.get("clustering", True)
            _sampling = _sub.get("sampling", True)
        except Exception:
            _clustering = _sampling = True
        if not _sampling:
            flat_lines: list[str] = []
            for c in cases:
                kn = c.get("knowledge") or {}
                if isinstance(kn, dict) and kn.get("error"):
                    flat_lines.append(f"- {tool}: {kn['error'][:LOG_TRUNC_200]}")
                else:
                    flat_lines.append(f"- {c.get('prompt', '')[:LOG_TRUNC_200]}")
            return "\n".join(flat_lines)
        clusters = [[c] for c in cases] if not _clustering else self._cluster_lean_cases(cases)
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
