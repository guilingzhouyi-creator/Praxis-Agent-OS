"""L3A — session management system.

Package structure:
  params.py     — constants
  model.py      — L3AModelConfig (model provider config, inheritance chain)
  types.py      — shared enums and dataclasses
  context.py    — ContextSource, ContextEpoch, ContextRegistry
  inbox.py      — PromptInbox (durable admission/promotion)
  pipeline.py   — ManagedToolOutput (oversized tool result spill)
  archive.py    — R4 archive store/restore
  session.py    — Session, SessionHistory, SessionManager
  helpers.py    — cardwrite handler, prompt builder, convergence
  api.py        — L2 Shell command routing
  __init__.py   — L3ADaemon lifecycle + re-exports + singleton

Architecture (above Cell, below L5 CLI):
  L3ADaemon (persistent process)
    ├── SessionManager (active session registry)
    ├── ContextRegistry (all context sources)
    └── L3AModelConfig (model config with inheritance)
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC
from typing import Any

from l3.error_bus import capture

from . import api as _api
from . import archive as _archive
from . import params as _p
from .context import ContextEpoch, ContextRegistry, ContextSource
from .model import L3AModelConfig
from .session import Session, SessionHistory, SessionManager
from .types import AssemblyMode, CardType, SessionRecord, TaskCard

logger = logging.getLogger(__name__)


def _build_default_registry() -> ContextRegistry:
    reg = ContextRegistry()
    try:
        from l3.memory.central_memory import get_l3a_memory as _gm
        def _mem_loader():
            try:
                return _gm().build_context(_p.AGENT_ID,
                    max_tokens=_p.MEMORY_MAX_TOKENS)
            except Exception:
                capture("l3a: memory context build failed", error_code="E_L3A_CTX", component="l3a")
                return ""
        reg.register(ContextSource(
            key="memory",
            loader=_mem_loader,
            render_baseline=lambda v: f"## Memory context\n{v}",
            render_update=lambda o, n: f"## Memory context (updated)\n{n}",
            render_removal=lambda: "## Memory context\n(no recent memory)",
        ))
    except Exception:
        capture("l3a: memory source registration skipped", error_code="E_L3A_CTX", component="l3a")
        logger.debug("l3a: memory source registration skipped")

    try:
        from l1.kernel.constitution import get_constitution as _gc
        reg.register(ContextSource(
            key="constitution",
            loader=lambda: _gc().summary(for_agent=_p.AGENT_ID),
            render_baseline=lambda v: f"## Rules\n{v}",
            render_update=lambda o, n: f"## Rules (updated)\n{n}",
        ))
    except Exception:
        capture("l3a: constitution source registration skipped", error_code="E_L3A_CTX", component="l3a")
        logger.debug("l3a: constitution source registration skipped")

    from datetime import datetime
    reg.register(ContextSource(
        key="system_time",
        loader=lambda: datetime.now(UTC).isoformat(),
        render_baseline=lambda v: f"## Current time\n{v}",
        render_update=lambda o, n: f"## Time updated\n{n}",
    ))

    reg.register(ContextSource(
        key="model_info",
        loader=lambda: _active_model.show(),
        render_baseline=lambda v: f"## Active model\nProvider: {v.get('provider','?')}  Model: {v.get('model','?')}",
        render_update=lambda o, n: f"## Model changed\nProvider: {o.get('provider','?')} -> {n.get('provider','?')}  Model: {o.get('model','?')} -> {n.get('model','?')}",
    ))

    reg.register(ContextSource(
        key="convergence",
        loader=lambda: _convergence_loader(),
        render_baseline=lambda v: _convergence_render(v),
        render_update=lambda o, n: _convergence_render(n),
    ))

    reg.register(ContextSource(
        key="l3a_memory",
        loader=lambda: _l3a_memory_loader(),
        render_baseline=lambda v: _l3a_memory_render(v),
        render_update=lambda o, n: _l3a_memory_render(n),
    ))

    return reg


def _l3a_memory_loader() -> list[dict]:
    """Load L3A's distilled deliberation summaries (bypass memory, latest 5)."""
    try:
        from .summaries import get_store
        return [s.to_dict() for s in get_store().latest(limit=5)]
    except Exception:
        capture("l3a: summaries loader failed", error_code="E_L3A_CTX", component="l3a")
        return []


def _l3a_memory_render(summaries: list[dict]) -> str:
    if not summaries:
        return "## L3A memory\n(no distilled deliberations yet)"
    lines = ["## L3A memory (recent deliberations)"]
    for s in summaries:
        lines.append(f"- [{s.get('issue_id', '?')}] {s.get('title', '')} "
                     f"(domain={s.get('domain', '')})")
        lines.append(f"  {s.get('summary', '')[:150]}")
    return "\n".join(lines)


def _convergence_loader() -> list[dict]:
    """Load pending convention/convergence items from all Cells."""
    try:
        from l3.cell import _cells
        from l3.discussion.cell_answer_repo import CellAnswerRepo
        items = []
        for cid in list(_cells.keys()):
            try:
                repo = CellAnswerRepo(cid, "")
                for a in repo.get_all():
                    items.append({"cell": cid, "agent_id": a.agent_id,
                                  "phase": a.phase, "type": a.answer_type,
                                  "created_at": a.created_at})
            except Exception:
                capture("l3a: cell answer repo read failed", error_code="E_L3A_CTX", component="l3a", context={"cell_id": cid})
                continue
        return items
    except Exception:
        capture("l3a: convergence loader failed", error_code="E_L3A_CTX", component="l3a")
        return []


def _convergence_render(items: list[dict]) -> str:
    if not items:
        return "## Convergence\n(no active convention discussions)"
    lines = ["## Convergence (active deliberations)"]
    for it in items[:10]:
        lines.append(f"- [{it['cell']}] {it['agent_id']} phase={it['phase']} type={it['type']}")
    return "\n".join(lines)


_active_model = L3AModelConfig()


class L3ADaemon:
    """L3A daemon — persistent process above Cell.

    Lifecycle:
      start() → background daemon thread
      tick()  → auto-close idle sessions, maintenance
      stop()  → join thread
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None
        self.manager = SessionManager()
        self.registry = _build_default_registry()
        self.model_config = _active_model
        self._pmu: Any = None
        self._sa_pool: Any = None
        self._init_pmu()
        self._init_subagent_pool()

    # ── Session API ──

    def _init_pmu(self) -> None:
        try:
            from l3.cell.components.cell_pmu import CellPmu
            self._pmu = CellPmu(cell_id="l3a")
        except Exception as e:
            capture("l3a: CellPmu init failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
            logger.debug("l3a: CellPmu init failed: %s", e)
            self._pmu = None

    def _init_subagent_pool(self) -> None:
        try:
            from .subagent import get_pool as _get_sa_pool
            self._sa_pool = _get_sa_pool()
        except Exception as e:
            capture("l3a: subagent pool init failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
            logger.debug("l3a: subagent pool init failed: %s", e)
            self._sa_pool = None

    def create_session(self, title: str = "") -> Session:
        """Create a new session wired with the daemon's model config and PMU."""
        s = self.manager.create(title=title, model_config=self.model_config,
                                registry=self.registry)
        if self._pmu:
            s.set_pmu(self._pmu)
        return s

    def get_session(self, session_id: str) -> Session | None:
        """Fetch an active session by id, or None when unknown."""
        return self.manager.get(session_id)

    def dispatch(self, args: list[str]) -> dict:
        """Route L2 shell args through the L3A command dispatcher and return its result dict."""
        return _api.dispatch(args, self.manager, self.registry,
                             self.model_config)

    def archive_search(self, limit: int = 10,
                       session_id: str | None = None) -> dict:
        """Search archived sessions and return their metadata entries."""
        return _archive.search_sessions(limit=limit, session_id=session_id)

    def archive_transcript(self, session_id: str) -> list[dict] | None:
        """Return the archived transcript for a session id, or None when absent."""
        return _archive.get_transcript(session_id)

    # ── Daemon lifecycle ──

    def start(self) -> dict:
        """Start the daemon thread and inject global LLM config, returning a result dict."""
        if self._running:
            return {"success": True, "note": "already running"}
        # Inject global LLM config before first session
        try:
            from l3.config.settings_center import get_center
            global_config = get_center().all()
            self.model_config.apply_global(global_config)
        except Exception:
            capture("l3a: global config injection failed", error_code="E_L3A_DAEMON", component="l3a")
            logger.debug("l3a: global config injection failed, using defaults")
        self._running = True
        self._thread = threading.Thread(target=self._daemon_loop,
                                        daemon=True, name="l3a-daemon")
        self._thread.start()
        logger.info("L3A daemon started")
        try:
            from l3.bus.log import get_service as _ls
            _ls().info("L3A daemon started", service="l3a")
        except Exception:
            logger.debug("l3a: log service unavailable at start, skipped", exc_info=True)
        return {"success": True}

    def stop(self) -> dict:
        """Stop the daemon thread and subagent pool, returning a result dict."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=_p.DAEMON_STOP_TIMEOUT)
            self._thread = None
        if self._sa_pool:
            try:
                self._sa_pool.shutdown(wait=True)
            except Exception:
                capture("l3a: subagent pool shutdown failed", error_code="E_L3A_DAEMON", component="l3a")
                logger.debug("l3a: subagent pool shutdown failed")
        logger.info("L3A daemon stopped")
        try:
            from l3.bus.log import get_service as _ls
            _ls().info("L3A daemon stopped", service="l3a")
        except Exception:
            logger.debug("l3a: log service unavailable at stop, skipped", exc_info=True)
        return {"success": True}

    def _daemon_loop(self) -> None:
        while self._running:
            time.sleep(_p.DAEMON_TICK_INTERVAL)
            if not self._running:
                break
            try:
                self.tick()
            except Exception as e:
                capture("L3A daemon tick failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
                logger.error("L3A daemon tick failed: %s", e)

    def tick(self) -> dict:
        """Run one maintenance pass (PMU, task sync, auto-compress, idle close) and return a summary dict."""
        results: dict[str, Any] = {}

        # Push PMU snapshot to StatsCenter
        if self._pmu:
            try:
                self._pmu.snapshot(force=True)
            except Exception as e:
                capture("l3a: PMU snapshot failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
                logger.debug("l3a: PMU snapshot failed: %s", e)

        # Watcher: reconcile session task tables with CardRegistry
        synced = 0
        for s in self.manager.list_active():
            sid = s.get("session_id", "")
            sess = self.manager.get(sid)
            if sess:
                try:
                    synced += sess.tasks.sync_from_registry()
                except Exception as e:
                    capture("l3a: task sync failed", error_code="E_L3A_DAEMON", component="l3a", context={"session_id": sid, "error": str(e)})
                    logger.debug("l3a: task sync failed for %s: %s", sid, e)
        if synced:
            results["tasks_synced"] = synced

        # Auto-compression monitor: check context pressure per session
        auto_compressed = 0
        for s in self.manager.list_active():
            sid = s.get("session_id", "")
            sess = self.manager.get(sid)
            if not sess:
                continue
            try:
                r = sess.auto_compress_check()
                if r.get("action") == "compressed":
                    auto_compressed += 1
                    self._auto_compressions = getattr(
                        self, "_auto_compressions", 0) + 1
                    results.setdefault("auto_compressed", []).append({
                        "session_id": sid,
                        "compressed": r.get("compressed", 0),
                        "pressure": r.get("pressure_before", 0),
                        "threshold": r.get("threshold", 0),
                    })
            except Exception as e:
                capture("l3a: auto-compress check failed", error_code="E_L3A_DAEMON", component="l3a", context={"session_id": sid, "error": str(e)})
                logger.debug("l3a: auto-compress failed for %s: %s", sid, e)
        if auto_compressed:
            results["auto_compressed_count"] = auto_compressed

        # Mer bypass: periodically aggregate multi-agent R1-R3 → symbolic Mer graph → controlled entry into R4
        # (toggled by memory.mer.enabled; bypass failure does not affect the main flow)
        try:
            from l3.memory.memory_mer import get_mer
            mer = get_mer()
            if mer.enabled:
                mr = mer.transform_and_archive()
                if mr.get("archived"):
                    results["mer_archived"] = mr["archived"]
                    results["mer_entries"] = mr.get("entries", 0)
        except Exception as e:
            capture("l3a: mer transform failed", error_code="E_L3A_DAEMON",
                    component="l3a", context={"error": str(e)})
            logger.debug("l3a: mer transform failed: %s", e)

        idle_timeout = _p.IDLE_TIMEOUT_DEFAULT
        try:
            from l3.config.settings_center import get_center
            idle_timeout = get_center().get("l3a.idle_timeout", _p.IDLE_TIMEOUT_DEFAULT)
        except Exception:
            capture("l3a: idle_timeout resolve failed", error_code="E_L3A_DAEMON", component="l3a")
            pass
        for s in self.manager.list_active():
            if s.get("status") != "active":
                continue
            last_active = s.get("last_active_at") or s.get("created_at", 0)
            idle = time.time() - last_active
            if idle > idle_timeout:
                sid = s.get("session_id", "")
                self.manager.close(sid)
                results.setdefault("auto_closed", []).append(sid)
                logger.info("L3A daemon: auto-closed idle session %s", sid)

        # Governance metrics: emit summary via MonitorBus
        active_sessions = self.manager.list_active()
        if active_sessions:
            results["governance"] = {
                "active_sessions": len(active_sessions),
                "total_turns": sum(s.get("turn_count", 0) for s in active_sessions),
                "total_cards": sum(s.get("card_count", 0) for s in active_sessions),
            }
            try:
                from l3.bus.monitor_bus import MonitorEvent as _ME
                from l3.bus.monitor_bus import get_bus as _mb
                _mb().emit(_ME(
                    type="l3a.governance",
                    source="l3a_daemon",
                    severity="info",
                    message=f"{results['governance']['active_sessions']} active sessions",
                    data=results["governance"],
                ))
            except Exception:
                capture("l3a: governance event emit failed", error_code="E_L3A_DAEMON", component="l3a")
                logger.debug("l3a: governance event emit failed")
        return results


# ── Module-level singleton ──

_daemon: L3ADaemon | None = None
_daemon_lock = threading.Lock()


def get_daemon() -> L3ADaemon:
    """Return the process-wide L3ADaemon singleton, creating it on first use."""
    global _daemon
    if _daemon is None:
        with _daemon_lock:
            if _daemon is None:
                _daemon = L3ADaemon()
    return _daemon


def reset_daemon() -> None:
    """Reset the singleton L3ADaemon instance (for testing)."""
    global _daemon
    if _daemon:
        _daemon.stop()
    _daemon = None


def start() -> dict:
    """Start the global L3A daemon and return its start result dict."""
    return get_daemon().start()


def stop() -> dict:
    """Stop and clear the global L3A daemon, returning a result dict."""
    global _daemon
    if _daemon is None:
        return {"success": True, "note": "not running"}
    r = _daemon.stop()
    _daemon = None
    return r


def dispatch(args: list[str] | None = None) -> dict:
    """Dispatch L3A shell args through the global daemon and return the result dict."""
    return get_daemon().dispatch(args or [])


# ── Re-exports ──
from .helpers import build_l3a_prompt, cardwrite_handler, get_convergence_queue
from .model import L3AModelConfig
from .subagent import L3ASubAgentPool
from .subagent import get_pool as get_l3a_pool
from .summaries import L3ASummary, L3ASummaryStore
from .summaries import get_store as get_summary_store
from .task_table import SessionTask, SessionTaskTable
from .types import L3ATask, L3ATaskGroup

start_l3a_daemon = start
stop_l3a_daemon = stop

__all__ = [
    "L3ADaemon",
    "Session",
    "SessionHistory",
    "SessionManager",
    "SessionConfig",
    "ContextEpoch",
    "ContextRegistry",
    "ContextSource",
    "L3AModelConfig",
    "AssemblyMode",
    "CardType",
    "SessionRecord",
    "TaskCard",
    "L3ATask",
    "L3ATaskGroup",
    "SessionTask",
    "SessionTaskTable",
    "L3ASummary",
    "L3ASummaryStore",
    "L3ASubAgentPool",
    "build_l3a_prompt",
    "cardwrite_handler",
    "get_convergence_queue",
    "get_daemon",
    "get_l3a_pool",
    "get_summary_store",
    "reset_daemon",
    "start",
    "stop",
    "dispatch",
    "start_l3a_daemon",
    "stop_l3a_daemon",
]
