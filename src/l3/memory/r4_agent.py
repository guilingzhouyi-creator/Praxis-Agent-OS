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
    R4_ROLE,
    R4_STALE_SCAN_LIMIT,
    R4_TERRITORY,
    SIGNAL_TARGET_L3,
)
from l1.kernel.params.system import (
    ARCHIVE_CHECK_INTERVAL,
    THREAD_JOIN_TIMEOUT,
)

from .r4_skill_evolution import SkillEvolutionMixin
from .r4_skill_feedback import SkillFeedbackMixin

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


class R4Agent(SkillEvolutionMixin, SkillFeedbackMixin):
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

    def __init__(
        self,
        interval: float = ARCHIVE_CHECK_INTERVAL,
        agent_id: str = "",
        role: str = "",
        territory: list[str] | None = None,
    ):
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
        self._skill_cache: dict[tuple, tuple] = {}
        # P3 lesson-summarization gates: per-tool cooldown + global throttle.
        self._last_summarize: dict[str, float] = {}
        self._last_summarize_any: float = 0.0
        # P4 skill-distillation gates (independent of summarization throttle).
        self._last_distill: dict[str, float] = {}
        # Reflexion-style failure-reflection gates (per-tool cooldown).
        self._last_reflect: dict[str, float] = {}
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
            allowed = gc.is_allowed("archive_ring3", agent_id=self.AGENT_ID, target="archive", territory=["archive"])
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

            # 4c. Curate evolved skills (contribution score + cap + retirement)
            curated = self._curate_skills()
            if curated:
                results["skills_curated"] = curated

            # 4d. Consistency: detect duplicate / contradictory evolved skills
            conflicts = self._detect_skill_conflicts()
            if conflicts:
                results["skill_conflicts"] = conflicts
                logger.info("R4Agent: %d skill conflict(s) detected", len(conflicts))

            # 5. Alert if issues found
            total_issues = len(stale) + len(contradictions)
            if total_issues > 0:
                self._total_alerts += total_issues
                from l1.kernel.params.agent import EVENT_ARCHIVE_ALERT

                emit_signal(
                    EVENT_ARCHIVE_ALERT,
                    sender="r4-agent",
                    target=SIGNAL_TARGET_L3,
                    data={"issues": total_issues, "stale": len(stale), "contradictions": len(contradictions)},
                )
                results["alerts"] = total_issues
                logger.info("R4Agent: %d archive issue(s) found, signal sent to L3A", total_issues)

        except Exception as e:
            logger.error("R4Agent tick error: %s", e)
            results["error"] = str(e)

        self._last_check = time.time()
        return results

    def status(self) -> dict:
        """Return R4Agent runtime status: loop state, counters, and timestamps."""
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
                stale.append(
                    {
                        "id": row[0],
                        "fonds": row[1],
                        "series": row[2],
                        "title": row[3],
                        "expired_since": now - (row[4] + row[5]),
                    }
                )
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
                contradictions.append(
                    {
                        "a": {"id": row[0], "fonds": row[1], "series": row[2], "title": row[3]},
                        "b": {"id": row[5], "fonds": row[6], "series": row[7]},
                    }
                )
        except Exception as e:
            logger.warning("R4Agent: consistency check failed: %s", e)
        return contradictions

    # ── Failure pattern tracking → lean case generation ──

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


_r4_agent: R4Agent | None = None


def get_r4_agent() -> R4Agent:
    """Get the R4Agent singleton, creating it on first call."""
    global _r4_agent
    if _r4_agent is None:
        _r4_agent = R4Agent()
    return _r4_agent


def start_r4_agent() -> dict:
    """Start the R4Agent singleton loop."""
    return get_r4_agent().start()


def stop_r4_agent() -> dict:
    """Stop the R4Agent singleton loop."""
    return get_r4_agent().stop()
