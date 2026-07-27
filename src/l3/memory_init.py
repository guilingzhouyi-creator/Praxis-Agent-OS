"""Memory Init — boot from memories / shutdown to memories lifecycle.

Agent OS boot  = reload agents from memories/AGENT/sessions snapshots
Agent OS shutdown = dump all runtime state into memories + recompile catalog

This is the init→shutdown closed loop: the memories directory IS the
root filesystem of the Agent OS.

Layout:
  memories/
    AGENT/sessions/{ts}_boot.json       ← runtime snapshot (what was booted)
    AGENT/sessions/{ts}_shutdown.json   ← shutdown dump (full state at exit)
    ops/alerts.json                     ← ops console alert history
    PHASE/{phase_id}/summary.md         ← phase tracking
    catalog.json                        ← auto-recompiled after shutdown

Usage:
  from l3.memory_init import init_from_memories, shutdown_to_memories
  init_from_memories()              # called by boot.py at boot time
  shutdown_to_memories()            # called at exit / shutdown command
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from l1.kernel.params.api import MEMORY_INIT_TIMEOUT
from l1.kernel.params.system import MEMORY_ALERT_EXPORT_LIMIT, AGENT_SESSION_TEMPLATE
from l1.kernel.paths import get_paths as _get_paths

logger = logging.getLogger(__name__)

MEMORIES_DIR = Path(_get_paths().memories_dir)
AGENT_SESSIONS_DIR = MEMORIES_DIR / "AGENT" / "sessions"
OPS_DIR = MEMORIES_DIR / "ops"
PHASE_DIR = MEMORIES_DIR / "PHASE"
DSL_DIR = MEMORIES_DIR / "DSL"
COMPILER_PATH = DSL_DIR / "compiler.py"

_SHUTDOWN_IN_PROGRESS = False


def _ensure_dirs() -> None:
    AGENT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    OPS_DIR.mkdir(parents=True, exist_ok=True)
    PHASE_DIR.mkdir(parents=True, exist_ok=True)


# ── Snapshot agent config ──

def _snapshot_path(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return str(AGENT_SESSIONS_DIR / AGENT_SESSION_TEMPLATE.format(ts=ts, prefix=prefix))


def _latest_snapshot() -> str | None:
    """Find the most recent boot snapshot in memories/AGENT/sessions/."""
    pattern = "*_boot.json"
    files = sorted(AGENT_SESSIONS_DIR.glob(pattern), reverse=True)
    return str(files[0]) if files else None


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, data: Any) -> bool:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warning("write failed %s: %s", path, e)
        return False


# ── Boot: load from memories ──

def init_from_memories() -> dict:
    """Attempt to load agent configuration from the latest boot snapshot.

    Returns:
      {"loaded": True, "agent_config": [...], "source": "memories/AGENT/sessions/..."}
      or {"loaded": False} if no snapshot exists.
    """
    _ensure_dirs()
    path = _latest_snapshot()
    if not path:
        return {"loaded": False, "reason": "no snapshot"}
    data = _read_json(path)
    if not data:
        return {"loaded": False, "reason": "invalid snapshot"}
    agent_config = data.get("agent_config", [])
    if not agent_config:
        return {"loaded": False, "reason": "empty agent_config"}

    logger.info("memories: loaded %d agents from %s", len(agent_config), path)
    return {
        "loaded": True,
        "agent_config": agent_config,
        "source": path,
        "snapshot_ts": data.get("timestamp", ""),
    }


def save_boot_snapshot(agent_config: list[tuple[str, str, list[str]]]) -> str | None:
    """Save current boot configuration to memories/AGENT/sessions/.

    This is called at the end of a successful boot so that a restart
    (or shutdown) can remember what was running.
    """
    _ensure_dirs()
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_config": agent_config,
        "version": 1,
    }
    path = _snapshot_path("boot")
    ok = _write_json(path, data)
    return path if ok else None


# ── Shutdown: dump all runtime state into memories ──

def shutdown_to_memories() -> dict:
    """Full system shutdown: dump all runtime state into memories.

    Dumps:
      - Agent session state (cells + terminals + ops alerts)
      - Ops console alert history
      - Runs DSL compiler to rebuild catalog.json
      - Cleans ephemeral temp state
      - Stops background services

    Safe to call multiple times (idempotent after first call).
    """
    global _SHUTDOWN_IN_PROGRESS
    if _SHUTDOWN_IN_PROGRESS:
        return {"success": True, "reason": "already shut down"}
    _SHUTDOWN_IN_PROGRESS = True
    _ensure_dirs()

    results = {}

    # 0. Persist MemoryManager Ring 2/3 (JSONL + SQLite)
    try:
        from .memory import get_memory
        mem = get_memory()
        mem.set_persist_dir(str(MEMORIES_DIR))
        pr = mem.persist()
        results["memory_persist"] = f"ring2={pr.get('short_written',0)} ring3={pr.get('long_written',0)}"
    except Exception as e:
        results["memory_persist"] = f"error: {e}"

    # 0b. Archive Ring 3 high-importance entries via ArchiveOrchestrator
    try:
        from .archive_orchestrator import archive_ring3
        n = archive_ring3(mem)
        results["archive_ring3"] = f"{n} archived"
    except Exception as e:
        results["archive_ring3"] = f"error: {e}"

    # 1. Snapshot all cells + agents
    try:
        from .cell import _cells, reset_cells
        snapshot = {}
        for cid, cell in list(_cells.items()):
            s = cell.stats()
            snapshot[cid] = {
                "agents": {
                    aid: {
                        "role": info.get("role", ""),
                        "ring": info.get("ring", 1),
                        "status": info.get("status", "IDLE"),
                        "active_scouts": info.get("active_scouts", 0),
                    }
                    for aid, info in s.get("agents", {}).items()
                },
            }
        if snapshot:
            path = _snapshot_path("shutdown")
            ok = _write_json(path, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cells": snapshot,
                "version": 1,
            })
            results["cell_snapshot"] = "ok" if ok else "write_failed"
        else:
            results["cell_snapshot"] = "no_cells"
    except Exception as e:
        results["cell_snapshot"] = f"error: {e}"

    # 2. Persist ops console alerts
    try:
        from .ops_console import get_ops
        ops = get_ops()
        alerts = ops.recent_alerts(limit=MEMORY_ALERT_EXPORT_LIMIT)
        if alerts:
            path = str(OPS_DIR / "alerts.json")
            _write_json(path, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "alerts": alerts,
            })
            results["ops_alerts"] = f"{len(alerts)} saved"
        else:
            results["ops_alerts"] = "no_alerts"
    except Exception as e:
        results["ops_alerts"] = f"error: {e}"

    # 3. Snapshot scout pool stats
    try:
        from .scout import get_pool
        pool = get_pool()
        s = pool.stats()
        results["scout_pool"] = f"active={s.get('active',0)} idle={s.get('idle',0)}"
    except Exception as e:
        results["scout_pool"] = f"error: {e}"

    # 4. Kill interrupts
    try:
        from l1.kernel.interrupt import get_table
        it = get_table()
        counts = it.counts()
        results["interrupts"] = dict(counts)
    except Exception as e:
        results["interrupts"] = f"error: {e}"

    # 5. Save kernel state (process table etc.)
    try:
        from l1.kernel.persist import save
        r = save()
        results["kernel_state"] = "ok" if r.get("success") else r.get("error", "fail")
    except Exception as e:
        results["kernel_state"] = f"error: {e}"

    # 6. Recompile catalog via DSL compiler
    if COMPILER_PATH.exists():
        try:
            compiler_result = subprocess.run(
                [sys.executable, str(COMPILER_PATH)],
                capture_output=True, text=True, timeout=MEMORY_INIT_TIMEOUT,
                cwd=str(MEMORIES_DIR.parent),
            )
            results["compiler"] = "ok" if compiler_result.returncode == 0 else compiler_result.stderr[:200]
        except Exception as e:
            results["compiler"] = f"error: {e}"
    else:
        results["compiler"] = "not_found"

    # 7. Reset cells + terminals
    try:
        from .agent_terminal import reset_terminals
        reset_terminals()
        from .cell import reset_cells
        reset_cells()
        results["reset"] = "ok"
    except Exception as e:
        results["reset"] = f"error: {e}"

    elapsed = round(time.time() - float(results.get("_start", time.time())), 3)
    logger.info("shutdown_to_memories complete: %s", results)
    return {"success": True, "results": results, "elapsed": elapsed}


def register_shutdown_handler() -> None:
    """Register atexit + signal handlers for graceful shutdown.

    Call once at boot time.  Will dump all state into memories on exit.
    """
    import atexit

    def _graceful_shutdown():
        if _SHUTDOWN_IN_PROGRESS:
            return
        print("\n⏻ Shutting down Agent OS...")
        try:
            r = shutdown_to_memories()
            status = "OK" if r.get("success") else "FAIL"
            print(f"  Shutdown {status}: {r.get('elapsed', 0):.2f}s")
            for k, v in r.get("results", {}).items():
                print(f"    {k}: {v}")
        except Exception as e:
            print(f"  Shutdown error: {e}")

    atexit.register(_graceful_shutdown)

    # Handle SIGTERM / SIGINT gracefully
    def _signal_handler(signum, frame):
        if _SHUTDOWN_IN_PROGRESS:
            return
        signame = signal.Signals(signum).name
        print(f"\n⏻ Caught {signame}, shutting down...")
        _graceful_shutdown()
        sys.exit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, AttributeError):
        pass  # not available in some contexts (Windows threads)

    logger.info("shutdown handler registered (atexit + signal)")
