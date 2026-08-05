"""R4Agent — background archive management Agent-Loop.

Part of the Four-Tier Hierarchical Memory Architecture:
  L0 Register → L1 Working → L2 Short-Term → L3 Long-Term → L4 Archive
                                            ↑
                                      R4Agent (narrow-scope Agent-Loop)

R4Agent is a light weight background agent that:
  - Periodically scans Archive for consistency (cross-reference, staleness)
  - Performs incremental archiving of Ring 3 entries (not only at shutdown)
  - Detects stale / contradictory archive entries and emits signals to L3A
  - Never writes to project files — only to Archive + memory Ring 3

Architecture:
  Trigger: timer (interval) + event (Ring 3 entry written)
  Tools:   read-only (Ring 1) + archive_write (dedicated)
  Scope:   Archive layer only — no project file access
  Output:  emit_signal("archive_alert", ...) → L3A
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel import emit_signal
from l1.kernel.params.agent import (
    R4_AGENT_ID,
    R4_CONSISTENCY_SCAN_LIMIT,
    R4_EVOLVED_SKILLS_DEFAULT,
    R4_LEAN_CASES_DEFAULT,
    R4_LEAN_GENERALIZE_THRESHOLD,
    R4_ROLE,
    R4_STALE_SCAN_LIMIT,
    R4_SUMMARIZE_COOLDOWN,
    R4_SUMMARIZE_MAX_TOKENS,
    R4_SUMMARIZE_MIN_INTERVAL,
    R4_SUMMARIZE_MIN_LEN,
    R4_TERRITORY,
    SIGNAL_TARGET_L3,
    SKILL_ARCHITECT_MAX_TOKENS,
)
from l1.kernel.params.system import (
    ARCHIVE_CHECK_INTERVAL,
    HASH_TRUNC_MEDIUM,
    LOG_TRUNC_30,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SKILL_TTL_DAYS,
    THREAD_JOIN_TIMEOUT,
)
from l3.services.model_service import get_service as _get_model_service

_MODEL_SPEC = "r4_agent"

def _resolve_model_spec() -> str:
    """Return model spec name, checking SettingsCenter first, then hardcoded default."""
    try:
        from l3.config.settings_center import get_center
        center = get_center()
        return str(center.get("r4_agent.model_spec", _MODEL_SPEC))
    except Exception:
        return _MODEL_SPEC

def _resolve_skill_scope() -> str:
    """Return evolution write scope: "project" (default) or "global".

    Reads ``skill.evolve_scope`` from SettingsCenter (set by cfg_skill from
    praxis.yaml).  Falls back to the paths singleton default.
    """
    try:
        from l1.kernel.paths import get_paths
        default = getattr(get_paths(), "skill_scope", "project")
    except Exception:
        default = "project"
    try:
        from l3.config.settings_center import get_center
        scope = str(get_center().get("skill.evolve_scope", default))
        return scope if scope in ("project", "global") else default
    except Exception:
        return default

logger = logging.getLogger(__name__)


class R4Agent:
    """Background archive management Agent-Loop.

    Identity: r4-agent/archivist — registered in process table (GateChain G2).
    Domain:   archive, memory — no project file access.
    Runs as a daemon thread. On each tick:
      1. Check identity (GateChain G2).
      2. Check for stale archive entries (expired TTL, never re-referenced).
      3. Incremental archive: export new Ring 3 entries (importance >= threshold).
      4. Consistency check: detect cross-fonds contradictions.
      5. Emit signal to L3A if issues found.
    """

    AGENT_ID = R4_AGENT_ID
    ROLE = R4_ROLE
    TERRITORY = list(R4_TERRITORY)

    def __init__(self, interval: float = ARCHIVE_CHECK_INTERVAL,
                 agent_id: str = "", role: str = "", territory: list[str] | None = None):
        self.interval = interval
        self.agent_id = agent_id or R4_AGENT_ID
        self.role = role or R4_ROLE
        self.territory = territory or list(R4_TERRITORY)
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_check: float = 0.0
        self._last_archive: float = 0.0
        self._total_archived = 0
        self._total_alerts = 0
        self._pmu: Any = None
        self._identity_verified = False
        # Injection cache: (key) → (skill_revision, result) — get_lean_cases /
        # get_evolved_skills results are cached until SkillManager structurally
        # mutates (revision bump), so AgentLoop._inject_extra_context skips the
        # O(N) registry scan + sort on every agent run.
        self._skill_cache: dict[tuple, tuple[int, list]] = {}
        # P3 lesson-summarization gates: per-tool cooldown + global throttle.
        self._last_summarize: dict[str, float] = {}
        self._last_summarize_any: float = 0.0
        self._registered = self._register_identity()

    def set_pmu(self, pmu: Any) -> None:
        """Attach a Performance Monitoring Unit for skill-evolution counters."""
        self._pmu = pmu

    def _register_identity(self) -> bool:
        """Register R4Agent in process table for GateChain G2 identity.
        Returns True if registration succeeded.
        """
        try:
            from l1.kernel.process import get_table
            pt = get_table()
            pt.spawn(name=self.AGENT_ID, role=self.ROLE, parent_pid=0, ring=1)
            logger.info("R4Agent registered in process table: %s/%s", self.AGENT_ID, self.ROLE)
            self._identity_verified = True
            return True
        except Exception as e:
            logger.warning("R4Agent process table registration failed: %s", e)
            return False

    # ── Lifecycle ──

    def start(self) -> dict:
        """Start the R4Agent background loop."""
        if self._running:
            return {"success": True, "note": "already running"}
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="r4-agent")
        self._thread.start()
        logger.info("R4Agent started (interval=%.0fs)", self.interval)
        return {"success": True}

    def stop(self) -> dict:
        """Stop the R4Agent background loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=THREAD_JOIN_TIMEOUT)
        logger.info("R4Agent stopped: %d archived, %d alerts", self._total_archived, self._total_alerts)
        return {"success": True, "archived": self._total_archived, "alerts": self._total_alerts}

    # ── Ticks ──

    def tick(self) -> dict:
        """Run one full check cycle with GateChain/Constitution gating."""
        results: dict[str, Any] = {"stale": [], "archived": 0, "contradictions": [], "alerts": 0}

        # ── GateChain G2 identity check ──
        if not self._identity_verified:
            results["error"] = "identity not verified"
            logger.warning("R4Agent tick blocked: identity not verified (register first)")
            return results

        # ── Constitution gate ──
        try:
            from l1.kernel.constitution import get_constitution
            gc = get_constitution()
            allowed = gc.is_allowed("archive_ring3", agent_id=self.AGENT_ID,
                                     target="archive", territory=["archive"])
            if not allowed.get("allowed", True):
                results["error"] = "constitution blocked"
                logger.warning("R4Agent tick blocked by constitution: %s", allowed.get("reason", ""))
                return results
        except Exception as e:
            logger.warning("R4Agent constitution check failed: %s", e)

        try:
            # 1. Stale detection
            stale = self._detect_stale()
            results["stale"] = stale

            # 2. Incremental archive
            archived = self._incremental_archive()
            results["archived"] = archived
            self._total_archived += archived

            # 3. Consistency check
            contradictions = self._check_consistency()
            results["contradictions"] = contradictions

            # 4. Process pending failure traces into lean cases
            processed = self._process_failure_traces()
            if processed:
                results["lean_cases_generated"] = processed

            # 4a. Clean up orphaned failure trace files (older than 24h, unresolved)
            cleaned = self._clean_orphan_traces()
            if cleaned:
                results["orphan_traces_cleaned"] = cleaned

            # 4b. Prune stale evolved skills (TTL check)
            pruned = self._prune_stale_skills()
            if pruned:
                results["skills_pruned"] = pruned

            # 5. Alert if issues found
            total_issues = len(stale) + len(contradictions)
            if total_issues > 0:
                self._total_alerts += total_issues
                from l1.kernel.params.agent import EVENT_ARCHIVE_ALERT
                emit_signal(EVENT_ARCHIVE_ALERT, sender="r4-agent", target=SIGNAL_TARGET_L3,
                            data={"issues": total_issues, "stale": len(stale),
                                  "contradictions": len(contradictions)})
                results["alerts"] = total_issues
                logger.info("R4Agent: %d archive issue(s) found, signal sent to L3A", total_issues)

        except Exception as e:
            logger.error("R4Agent tick error: %s", e)
            results["error"] = str(e)

        self._last_check = time.time()
        return results

    def status(self) -> dict:
        return {
            "running": self._running,
            "interval": self.interval,
            "last_check": self._last_check,
            "last_archive": self._last_archive,
            "total_archived": self._total_archived,
            "total_alerts": self._total_alerts,
        }

    # ── Loop ──

    def _loop(self) -> None:
        while self._running:
            time.sleep(self.interval)
            if not self._running:
                break
            try:
                self.tick()
            except Exception as e:
                logger.error("R4Agent loop error: %s", e)

    # ── Checks (delegated to archive_orchestrator) ──

    def _detect_stale(self) -> list[dict]:
        """Find archive entries with expired TTL or no recent references."""
        from l3.tools._archive import _get_db
        stale = []
        try:
            conn = _get_db()
            now = time.time()
            rows = conn.execute(
                "SELECT id, fonds, series, title, ttl, created_at "
                "FROM archive WHERE ttl > 0 AND (created_at + ttl) < ? "
                f"ORDER BY created_at ASC LIMIT {R4_STALE_SCAN_LIMIT}",
                (now,),
            ).fetchall()
            for row in rows:
                stale.append({"id": row[0], "fonds": row[1], "series": row[2],
                              "title": row[3], "expired_since": now - (row[4] + row[5])})
        except Exception as e:
            logger.warning("R4Agent: stale detection failed: %s", e)
        return stale

    def _incremental_archive(self) -> int:
        """Export new Ring 3 entries to Archive since last run."""
        try:
            from .archive_orchestrator import archive_ring3
            from .memory import get_memory
            mem = get_memory()
            return archive_ring3(mem)
        except Exception as e:
            logger.warning("R4Agent: incremental archive failed: %s", e)
            return 0

    def restore_ring3(self, limit: int = 100) -> dict:
        """Restore archived entries back into Ring 3 knowledge.

        Delegates to archive_orchestrator.ring3_from_archive().
        Called by boot.py during system startup to warm up Ring 3.

        Args:
            limit: Max entries to restore (default 100).

        Returns:
            {"success": bool, "restored": int}
        """
        try:
            from .archive_orchestrator import ring3_from_archive
            from .memory import get_memory
            mem = get_memory()
            count = ring3_from_archive(mem)
            return {"success": True, "restored": count}
        except Exception as e:
            logger.warning("R4Agent: restore_ring3 failed: %s", e)
            return {"success": False, "error": str(e)}

    def _check_consistency(self) -> list[dict]:
        """Detect cross-fonds contradictions in Archive."""
        from l3.tools._archive import _get_db
        contradictions = []
        try:
            conn = _get_db()
            rows = conn.execute(
                "SELECT a.id, a.fonds, a.series, a.title, a.content, "
                "b.id, b.fonds, b.series "
                "FROM archive a JOIN archive b ON a.title = b.title "
                "AND a.id != b.id AND a.content != b.content "
                f"LIMIT {R4_CONSISTENCY_SCAN_LIMIT}",
            ).fetchall()
            for row in rows:
                contradictions.append({
                    "a": {"id": row[0], "fonds": row[1], "series": row[2], "title": row[3]},
                    "b": {"id": row[5], "fonds": row[6], "series": row[7]},
                })
        except Exception as e:
            logger.warning("R4Agent: consistency check failed: %s", e)
        return contradictions

    # ── Failure pattern tracking → lean case generation ──

    def _track_failure(self, agent_id: str, tool_name: str,
                       args: dict, error: str, turn_log: list[dict]) -> None:
        """Record a tool call failure for later analysis and lean case generation."""
        try:
            import json
            import os

            from l1.kernel.params.system import SKILL_LEAN_CASE_TEMPLATE
            from l1.kernel.paths import get_paths as _gp
            lean_dir = _gp().skill_lean_dir
            entry = {
                "agent_id": agent_id, "tool": tool_name, "args": args,
                "error": error[:LOG_TRUNC_200], "timestamp": time.time(),
                "turn_count": len(turn_log),
                "resolved": False,
            }
            os.makedirs(lean_dir, exist_ok=True)
            fp = os.path.join(lean_dir, SKILL_LEAN_CASE_TEMPLATE.format(
                agent_id=agent_id, tool_name=tool_name, ts=int(time.time())))
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2)
            # R4 archive: persist the raw failure trace so a generated lean case
            # can be traced back to "why it exists" (audit trail).
            try:
                from l3.tools._archive import _cmd_archive_store
                _cmd_archive_store(
                    fonds="skills", series="lean_trace",
                    content=json.dumps(entry, ensure_ascii=False)[:LOG_TRUNC_2000],
                    tags=f"{agent_id},{tool_name},failure",
                )
            except Exception as e:
                logger.debug("R4Agent: archive failure trace skipped: %s", e)
        except Exception as e:
            logger.warning("R4Agent: track failure failed: %s", e)

    def track_tool_failure(self, agent_id: str, tool_name: str,
                           args: dict, error: str, turn_log: list[dict]) -> None:
        """Public entry for the tool pipeline — records a failure for lean-case generation."""
        self._track_failure(agent_id=agent_id, tool_name=tool_name,
                            args=args, error=error, turn_log=turn_log)

    def _process_failure_traces(self) -> int:
        """Scan pending failure traces and generate lean case Skill entries.

        Features:
          - Deduplication: same tool+agent entries are merged into one lean case.
          - Atomic write: resolved flag is written via tempfile+rename.
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
            for s in sm.list(tags=["lean_case"]):
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
                    sm.create(
                        name=skill_name,
                        description=f"Failure case: {tool} — {entry['error'][:LOG_TRUNC_60]}",
                        prompt=lean_text,
                        tags=["lean_case", "failure", agent, tool],
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
                                logger.info("R4Agent: failure for %s hits evolved skill '%s' — refine hint",
                                            tool, h["name"])
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

    def _skill_md_path(self, name: str) -> str:
        """Resolve the SKILL.md path for a skill in the evolved dir.

        Layered persistence: project scope → travels with the repo; global
        scope → machine-local data dir (must match the boot discovery dirs).
        """
        import os

        from l1.kernel.paths import get_paths as _gp
        scope = _resolve_skill_scope()
        evolved_base = (_gp().skill_project_evolved_dir if scope == "project"
                        else _gp().skill_evolved_dir)
        return os.path.join(evolved_base, name, "SKILL.md")

    def _persist_skill_md(self, name: str, description: str, prompt: str,
                          tags: list[str], allowed_tools: list[str] | None = None,
                          rules: list[str] | None = None,
                          procedures: list[dict] | None = None,
                          variables: dict | None = None) -> str:
        """Persist a skill as SKILL.md with round-trip frontmatter.

        Frontmatter carries name/description/tags/allowed_tools/variables so a
        reload via SkillManager._load_markdown() restores them; the prompt is
        the body.  Shared by evolve_skill (LLM) and _generalize_lean_cases
        (rule-based) so both survive restart via the boot discovery dirs.
        """
        import os

        import yaml as _yaml
        md_path = self._skill_md_path(name)
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        meta = {"name": name, "description": description, "tags": tags}
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
    def _atomic_write(fp: str, data: dict) -> None:
        """Write JSON atomically via tempfile+rename to avoid partial reads."""
        import json
        import os
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(fp), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, fp)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                logger.debug("R4Agent: temp file cleanup failed, ignored", exc_info=True)
            raise

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

    def get_lean_cases(self, agent_id: str = "", tool_name: str = "",
                       cell_id: str = "", limit: int = R4_LEAN_CASES_DEFAULT) -> list[str]:
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
        skills = sm.list(tags=tags, limit=limit * 2, sort_by="loaded_at")
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

    def get_lean_case_names(self, agent_id: str = "", tool_name: str = "",
                            cell_id: str = "", limit: int = R4_LEAN_CASES_DEFAULT) -> list[str]:
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

    def get_evolved_skills(self, agent_id: str = "", cell_id: str = "",
                           limit: int = R4_EVOLVED_SKILLS_DEFAULT, graph_diffusion: bool = False) -> list[dict]:
        """Retrieve evolved skills for injection into AgentLoop prompts.

        Filters by agent_id if provided (strict tag membership, not OR-match).
        When ``cell_id`` has a bound white-list, only white-listed skills are
        returned (unbound cells fall back to the global pool).  Returns most
        recently loaded skills first.
        """
        from l1.kernel.skill import get_skill_manager
        sm = get_skill_manager()
        cache_key = ("evolved", agent_id, cell_id, limit, graph_diffusion)
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
                            evolved.append({
                                "name": s["name"],
                                "description": s.get("description", ""),
                                "prompt": s["prompt"],
                            })
                    if evolved:
                        return evolved[:limit]
            except Exception as e:
                logger.debug("R4Agent: graph diffusion fallback to linear: %s", e)
        skills = sm.list(tags=["evolved"], limit=limit * 2, sort_by="loaded_at")
        evolved = []
        for s in skills:
            if agent_id and agent_id not in s.get("tags", []):
                continue
            if allow and s["name"] not in allow:
                continue
            if s.get("prompt"):
                evolved.append({
                    "name": s["name"],
                    "description": s.get("description", ""),
                    "prompt": s["prompt"],
                })
        evolved = evolved[:limit]
        self._skill_cache[cache_key] = (rev, evolved)
        return evolved

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

            scope = _resolve_skill_scope()
            # Persist as SKILL.md — shared helper keeps round-trip frontmatter
            # (tags/allowed_tools/variables survive reload) for both the LLM
            # evolve path and the rule-based generalization path.
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


_r4_agent: R4Agent | None = None


def get_r4_agent() -> R4Agent:
    global _r4_agent
    if _r4_agent is None:
        _r4_agent = R4Agent()
    return _r4_agent


def start_r4_agent() -> dict:
    return get_r4_agent().start()


def stop_r4_agent() -> dict:
    return get_r4_agent().stop()
