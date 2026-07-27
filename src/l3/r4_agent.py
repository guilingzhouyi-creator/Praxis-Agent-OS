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

from l3.model_service import get_service as _get_model_service

from l1.kernel import emit_signal
from l1.kernel.params.agent import R4_AGENT_ID, R4_ROLE, R4_TERRITORY
from l1.kernel.params.system import ARCHIVE_CHECK_INTERVAL

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
        self._identity_verified = False
        self._registered = self._register_identity()

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
            self._thread.join(timeout=5)
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

            # 5. Alert if issues found
            total_issues = len(stale) + len(contradictions)
            if total_issues > 0:
                self._total_alerts += total_issues
                from l1.kernel.params.agent import EVENT_ARCHIVE_ALERT
                emit_signal(EVENT_ARCHIVE_ALERT, sender="r4-agent", target="l3",
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
        from tools._archive import _get_db
        stale = []
        try:
            conn = _get_db()
            now = time.time()
            rows = conn.execute(
                "SELECT id, fonds, series, title, ttl, created_at "
                "FROM archive WHERE ttl > 0 AND (created_at + ttl) < ? "
                "ORDER BY created_at ASC LIMIT 50",
                (now,),
            ).fetchall()
            conn.close()
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
        from tools._archive import _get_db
        contradictions = []
        try:
            conn = _get_db()
            # Simple check: find entries with same title but different content
            rows = conn.execute(
                "SELECT a.id, a.fonds, a.series, a.title, a.content, "
                "b.id, b.fonds, b.series "
                "FROM archive a JOIN archive b ON a.title = b.title "
                "AND a.id != b.id AND a.content != b.content "
                "LIMIT 20",
            ).fetchall()
            conn.close()
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
            from l1.kernel.paths import get_paths as _gp
            from l1.kernel.params.system import SKILL_LEAN_CASE_TEMPLATE
            import json, os
            lean_dir = _gp().skill_lean_dir
            entry = {
                "agent_id": agent_id, "tool": tool_name, "args": args,
                "error": error[:200], "timestamp": time.time(),
                "turn_count": len(turn_log),
                "resolved": False,
            }
            os.makedirs(lean_dir, exist_ok=True)
            fp = os.path.join(lean_dir, SKILL_LEAN_CASE_TEMPLATE.format(
                agent_id=agent_id, tool_name=tool_name, ts=int(time.time())))
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2)
        except Exception as e:
            logger.warning("R4Agent: track failure failed: %s", e)

    def _process_failure_traces(self) -> int:
        """Scan pending failure traces and generate lean case Skill entries."""
        import json, os
        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager

        lean_dir = _gp().skill_lean_dir
        processed = 0
        try:
            if not os.path.isdir(lean_dir):
                return 0
            for fn in os.listdir(lean_dir):
                if not fn.endswith(".json"):
                    continue
                fp = os.path.join(lean_dir, fn)
                try:
                    with open(fp, encoding="utf-8") as f:
                        entry = json.load(f)
                    if entry.get("resolved"):
                        continue
                    # Generate lean case: "tool X failed with error Y because of Z"
                    lean_text = (
                        f"When using {entry['tool']} with {entry['args']}, "
                        f"it failed: {entry['error']}. "
                        f"Avoid this pattern after {entry['turn_count']} turns."
                    )
                    sm = get_skill_manager()
                    sm.create(
                        name=f"fail_{entry['tool']}_{int(entry['timestamp'])}",
                        description=f"Failure case: {entry['tool']} — {entry['error'][:60]}",
                        prompt=lean_text,
                        tags=["lean_case", "failure", entry["agent_id"], entry["tool"]],
                    )
                    entry["resolved"] = True
                    with open(fp, "w", encoding="utf-8") as f:
                        json.dump(entry, f, indent=2)
                    processed += 1
                except Exception as e:
                    logger.warning("R4Agent: process trace %s failed: %s", fn, e)
        except Exception as e:
            logger.warning("R4Agent: process failure traces failed: %s", e)
        return processed

    def get_lean_cases(self, agent_id: str = "", tool_name: str = "",
                       limit: int = 5) -> list[str]:
        """Retrieve lean failure cases for injection into AgentLoop prompts."""
        from l1.kernel.skill import get_skill_manager
        sm = get_skill_manager()
        tags = ["lean_case"]
        if agent_id:
            tags.append(agent_id)
        if tool_name:
            tags.append(tool_name)
        skills = sm.list(tags=tags, limit=limit)
        return [s["prompt"] for s in skills if s.get("prompt")][:limit]

    def get_evolved_skills(self, agent_id: str = "", limit: int = 3) -> list[dict]:
        """Retrieve evolved skills for injection into AgentLoop prompts."""
        from l1.kernel.skill import get_skill_manager
        sm = get_skill_manager()
        skills = sm.list(tags=["evolved"], limit=limit * 2)
        evolved = []
        for s in skills:
            if s.get("prompt"):
                evolved.append({
                    "name": s["name"],
                    "description": s.get("description", ""),
                    "prompt": s["prompt"],
                })
        return evolved[:limit]

    def evolve_skill(self, intent: str) -> dict:
        """Use LLM to generate a new skill definition from a natural language intent.

        Uses the LLM engine to produce a structured skill (name, description, rules,
        procedures, system prompt), then registers it with SkillManager and persists
        it as a SKILL.md file in the evolved skills directory.

        Invoked via: /skills evolve <intent>
        """
        if not intent or not intent.strip():
            return {"success": False, "error": "usage: /skills evolve <description>"}

        try:
            from l4.llm import get_engine
            from l1.kernel.prompts import get_prompt
            from l1.kernel.skill import get_skill_manager
            import json, os
            from l1.kernel.paths import get_paths as _gp

            system = get_prompt("r4_agent.skill_architect", "")
            prompt = f"Create a skill for: {intent.strip()}"
            engine = get_engine()
            result = engine.generate(prompt=prompt, system=system, max_tokens=2048,
                                     user_id="r4-agent",
                                     **_get_model_service().resolve_dict("r4_agent"))

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
            sm.create(
                name=name,
                description=skill_def.get("description", ""),
                prompt=skill_def.get("prompt", ""),
                tags=skill_def.get("tags", ["evolved"]) + ["evolved"],
                rules=skill_def.get("rules", []),
                procedures=skill_def.get("procedures", []),
            )

            # Persist as SKILL.md
            skill_dir = os.path.join(_gp().skill_evolved_dir, name)
            os.makedirs(skill_dir, exist_ok=True)
            md_path = os.path.join(skill_dir, "SKILL.md")
            md_lines = ["---"]
            md_lines.append(f"name: {name}")
            md_lines.append(f"description: {skill_def.get('description', '')}")
            md_lines.append("disable-model-invocation: true")
            md_lines.append("---")
            md_lines.append("")
            md_lines.append(skill_def.get("prompt", ""))
            md_lines.append("")
            if skill_def.get("rules"):
                md_lines.append("## Rules")
                for rule in skill_def["rules"]:
                    md_lines.append(f"- {rule}")
                md_lines.append("")
            if skill_def.get("procedures"):
                md_lines.append("## Procedures")
                for proc in skill_def["procedures"]:
                    md_lines.append(f"- **{proc.get('step', '?')}**: {proc.get('description', '')}")
                md_lines.append("")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))

            logger.info("R4Agent: evolved skill '%s' from intent: %.80s", name, intent)
            return {
                "success": True,
                "skill": name,
                "description": skill_def.get("description", ""),
                "rules": len(skill_def.get("rules", [])),
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
