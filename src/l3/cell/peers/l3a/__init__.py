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
from typing import Any

from . import params as _p
from .model import L3AModelConfig
from .types import AssemblyMode, CardType, TaskCard, SessionRecord
from .context import ContextRegistry, ContextSource, ContextEpoch
from .session import Session, SessionManager, SessionHistory
from . import archive as _archive
from . import api as _api
from l3.error_bus import capture

logger = logging.getLogger(__name__)


def _build_default_registry() -> ContextRegistry:
    reg = ContextRegistry()
    try:
        from l3.memory.memory import get_memory as _gm
        def _mem_loader():
            try:
                return _gm().build_context(_p.AGENT_ID,
                    max_tokens=_p.MEMORY_MAX_TOKENS)
            except Exception:
                return ""
        reg.register(ContextSource(
            key="memory",
            loader=_mem_loader,
            render_baseline=lambda v: f"## Memory context\n{v}",
            render_update=lambda o, n: f"## Memory context (updated)\n{n}",
            render_removal=lambda: "## Memory context\n(no recent memory)",
        ))
    except Exception:
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
        logger.debug("l3a: constitution source registration skipped")

    from datetime import datetime, timezone
    reg.register(ContextSource(
        key="system_time",
        loader=lambda: datetime.now(timezone.utc).isoformat(),
        render_baseline=lambda v: f"## Current time\n{v}",
        render_update=lambda o, n: f"## Time updated\n{n}",
    ))

    reg.register(ContextSource(
        key="model_info",
        loader=lambda: _active_model.show(),
        render_baseline=lambda v: f"## Active model\nProvider: {v.get('provider','?')}  Model: {v.get('model','?')}",
        render_update=lambda o, n: f"## Model changed\nProvider: {o.get('provider','?')} -> {n.get('provider','?')}  Model: {o.get('model','?')} -> {n.get('model','?')}",
    ))

    return reg


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
        self._init_pmu()
        self._init_subagent_pool()

    # ── Session API ──

    def _init_pmu(self) -> None:
        try:
            from l3.cell.components.cell_pmu import CellPmu
            self._pmu = CellPmu(cell_id="l3a")
        except Exception as e:
            logger.debug("l3a: CellPmu init failed: %s", e)
            self._pmu = None

    def _init_subagent_pool(self) -> None:
        try:
            from .subagent import get_pool as _get_sa_pool
            self._sa_pool = _get_sa_pool()
        except Exception as e:
            logger.debug("l3a: subagent pool init failed: %s", e)
            self._sa_pool = None

    def create_session(self, title: str = "") -> Session:
        s = self.manager.create(title=title, model_config=self.model_config,
                                registry=self.registry)
        if self._pmu:
            s.set_pmu(self._pmu)
        return s

    def get_session(self, session_id: str) -> Session | None:
        return self.manager.get(session_id)

    def dispatch(self, args: list[str]) -> dict:
        return _api.dispatch(args, self.manager, self.registry,
                             self.model_config)

    def archive_search(self, limit: int = 10,
                       session_id: str | None = None) -> dict:
        return _archive.search_sessions(limit=limit, session_id=session_id)

    def archive_transcript(self, session_id: str) -> list[dict] | None:
        return _archive.get_transcript(session_id)

    # ── Daemon lifecycle ──

    def start(self) -> dict:
        if self._running:
            return {"success": True, "note": "already running"}
        # Inject global LLM config before first session
        try:
            from l3.config.settings_center import get_center
            global_config = get_center().all()
            self.model_config.apply_global(global_config)
        except Exception:
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
            pass
        return {"success": True}

    def stop(self) -> dict:
        self._running = False
        if self._thread:
            self._thread.join(timeout=_p.DAEMON_STOP_TIMEOUT)
            self._thread = None
        if self._sa_pool:
            try:
                self._sa_pool.shutdown(wait=True)
            except Exception:
                logger.debug("l3a: subagent pool shutdown failed")
        logger.info("L3A daemon stopped")
        try:
            from l3.bus.log import get_service as _ls
            _ls().info("L3A daemon stopped", service="l3a")
        except Exception:
            pass
        return {"success": True}

    def _daemon_loop(self) -> None:
        while self._running:
            time.sleep(_p.DAEMON_TICK_INTERVAL)
            if not self._running:
                break
            try:
                self.tick()
            except Exception as e:
                logger.error("L3A daemon tick failed: %s", e)

    def tick(self) -> dict:
        results: dict[str, Any] = {}

        # Push PMU snapshot to StatsCenter
        if self._pmu:
            try:
                self._pmu.snapshot(force=True)
            except Exception as e:
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
                    logger.debug("l3a: task sync failed for %s: %s", sid, e)
        if synced:
            results["tasks_synced"] = synced

        idle_timeout = _p.IDLE_TIMEOUT_DEFAULT
        try:
            from l3.config.settings_center import get_center
            idle_timeout = get_center().get("l3a.idle_timeout", _p.IDLE_TIMEOUT_DEFAULT)
        except Exception:
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
                from l3.bus.monitor_bus import MonitorEvent as _ME, get_bus as _mb
                _mb().emit(_ME(
                    type="l3a.governance",
                    source="l3a_daemon",
                    severity="info",
                    message=f"{results['governance']['active_sessions']} active sessions",
                    data=results["governance"],
                ))
            except Exception:
                logger.debug("l3a: governance event emit failed")
        return results


# ── Module-level singleton ──

_daemon: L3ADaemon | None = None
_daemon_lock = threading.Lock()


def get_daemon() -> L3ADaemon:
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
    return get_daemon().start()


def stop() -> dict:
    global _daemon
    if _daemon is None:
        return {"success": True, "note": "not running"}
    r = _daemon.stop()
    _daemon = None
    return r


def dispatch(args: list[str] | None = None) -> dict:
    return get_daemon().dispatch(args or [])


# ── Re-exports ──
from .types import AssemblyMode, CardType, TaskCard, SessionRecord, L3ATask, L3ATaskGroup
from .helpers import get_convergence_queue, cardwrite_handler, build_l3a_prompt
from .model import L3AModelConfig
from .context import ContextSource, ContextRegistry, ContextEpoch
from .session import Session, SessionManager, SessionHistory
from .task_table import SessionTaskTable, SessionTask
from .subagent import L3ASubAgentPool, get_pool as get_l3a_pool
from . import params as l3a_params

start_l3a_daemon = start
stop_l3a_daemon = stop
