"""Fault tolerance — checkpoint, crash recovery, autonomous mode.

Agent OS spec §5:
  5.1 Agent crash recovery — checkpoint → restart → restore
  5.2 Scout timeout — retry → fallback
  5.3 L3 unreachable — autonomous mode → periodic reconnect
  5.4 Constitution conflict — freeze → human arbitration
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from l3._base import BaseService
from l1.kernel.params.system import PRAXIS_CONFIG_DIR

logger = logging.getLogger(__name__)

from l1.kernel.platform import get_config_dir
CHECKPOINT_DIR = Path(get_config_dir()) / "checkpoints"

# Import configurable constants from kernel params
from l1.kernel.params.system import (
    HEARTBEAT_TIMEOUT,
    CRASH_TIMEOUT,
    FAULT_CHECK_INTERVAL,
    FAULT_RETRY_INTERVAL,
)
AUTONOMOUS_RECONNECT_INTERVAL = 5.0  # Autonomous mode reconnect interval


@dataclass
class Checkpoint:
    """Agent checkpoint — saved state for crash recovery."""
    agent_id: str
    task_id: str = ""
    task_status: str = ""          # pending | running | done
    progress: dict = field(default_factory=dict)
    tool_ring_snapshot: list = field(default_factory=list)
    sandbox_files: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> Checkpoint:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AgentHeartbeat:
    """Agent heartbeat record."""
    agent_id: str
    last_seen: float = field(default_factory=time.time)
    status: str = "alive"          # alive | unresponsive | crashed
    task_id: str = ""
    consecutive_failures: int = 0


class FaultToleranceService(BaseService):
    """Fault tolerance — checkpoint, crash recovery, autonomous mode.

    Spec §5.1 — Agent crash recovery:
      T+0:  L3 detects heartbeat loss
      T+15: Mark UNRESPONSIVE
      T+30: Mark CRASHED → checkpoint restore → restart

    Spec §5.3 — L3 unreachable:
      L3 down → autonomous mode → current tasks continue → periodic reconnect
    """

    def __init__(self):
        super().__init__("fault_tolerance")
        self._checkpoints: dict[str, Checkpoint] = {}
        self._heartbeats: dict[str, AgentHeartbeat] = {}
        self._lock = threading.RLock()
        self._monitor_thread: threading.Thread | None = None
        self._running = False
        self._autonomous_mode = False
        self._l3_reachable = True
        self._recovery_hooks: list[Callable] = []

    def _on_start(self) -> dict:
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("fault_tolerance started")
        return {"success": True}

    def _on_stop(self) -> dict:
        self._running = False
        return {"success": True}

    def on_recovery(self, hook: Callable) -> None:
        """Register a crash recovery hook."""
        with self._lock:
            self._recovery_hooks.append(hook)

    # ── Heartbeat ──

    def heartbeat(self, agent_id: str, task_id: str = "") -> dict:
        """Agent heartbeat — called periodically by Agent."""
        with self._lock:
            hb = self._heartbeats.get(agent_id)
            if hb:
                hb.last_seen = time.time()
                hb.status = "alive"
                hb.task_id = task_id
                hb.consecutive_failures = 0
            else:
                self._heartbeats[agent_id] = AgentHeartbeat(
                    agent_id=agent_id, task_id=task_id,
                )
        return {"success": True, "agent_id": agent_id, "interval": HEARTBEAT_TIMEOUT}

    def get_heartbeat(self, agent_id: str) -> dict:
        """Query agent heartbeat status."""
        with self._lock:
            hb = self._heartbeats.get(agent_id)
            if not hb:
                return {"success": True, "agent_id": agent_id, "status": "unknown"}
            now = time.time()
            elapsed = now - hb.last_seen
            if elapsed > CRASH_TIMEOUT:
                status = "crashed"
            elif elapsed > HEARTBEAT_TIMEOUT:
                status = "unresponsive"
            else:
                status = "alive"
            return {
                "success": True, "agent_id": agent_id, "status": status,
                "last_seen": hb.last_seen, "elapsed": round(elapsed, 1),
                "task_id": hb.task_id,
            }

    # ── Checkpoint ──

    def save_checkpoint(self, agent_id: str, task_id: str = "",
                        progress: dict | None = None,
                        sandbox_files: list[str] | None = None) -> dict:
        """Save agent checkpoint (§5.1)."""
        cp = Checkpoint(
            agent_id=agent_id, task_id=task_id, task_status="running",
            progress=progress or {}, sandbox_files=sandbox_files or [],
        )
        with self._lock:
            self._checkpoints[agent_id] = cp
        # Persist to disk
        self._persist_checkpoint(cp)
        return {"success": True, "agent_id": agent_id, "checkpoint_id": cp.created_at}

    def restore_checkpoint(self, agent_id: str) -> dict:
        """Restore agent from last checkpoint (§5.1)."""
        with self._lock:
            cp = self._checkpoints.get(agent_id)
            if not cp:
                # Try disk
                cp = self._load_checkpoint(agent_id)
                if not cp:
                    return {"success": False, "error": "no checkpoint found"}
                self._checkpoints[agent_id] = cp
        return {"success": True, "checkpoint": cp.to_dict()}

    def mark_done(self, agent_id: str) -> dict:
        """Mark task as done (checkpoint no longer needed)."""
        with self._lock:
            self._checkpoints.pop(agent_id, None)
        self._delete_checkpoint(agent_id)
        return {"success": True}

    def _persist_checkpoint(self, cp: Checkpoint) -> None:
        try:
            path = CHECKPOINT_DIR / f"{cp.agent_id}.json"
            path.write_text(json.dumps(cp.to_dict(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("checkpoint persist failed: %s", e)

    def _load_checkpoint(self, agent_id: str) -> Checkpoint | None:
        try:
            path = CHECKPOINT_DIR / f"{agent_id}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return Checkpoint.from_dict(data)
        except Exception as e:
            logger.warning("checkpoint load failed: %s", e)
        return None

    def _delete_checkpoint(self, agent_id: str) -> None:
        try:
            path = CHECKPOINT_DIR / f"{agent_id}.json"
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning("services/fault_tolerance: %s", e)

    # ── Crash Recovery (§5.1) ──

    def on_agent_crash(self, agent_id: str) -> dict:
        """Handle agent crash: save state → notify → restore."""
        logger.warning("agent crash detected: %s", agent_id)
        # 1. Save final checkpoint
        cp = self._checkpoints.get(agent_id)
        if cp:
            self._persist_checkpoint(cp)
        # 2. Notify hooks
        for hook in self._recovery_hooks:
            try:
                hook(agent_id)
            except Exception as e:
                logger.warning("fault_tolerance: %s", e)
        # 3. Auto-restart
        if cp:
            r = self.restore_checkpoint(agent_id)
            if r["success"]:
                logger.info("agent %s restored from checkpoint", agent_id)
                return {"success": True, "action": "restored", "checkpoint": cp.to_dict()}
        return {"success": True, "action": "cold_start", "note": "no checkpoint, fresh start"}

    # ── Autonomous Mode (§5.3) ──

    def set_l3_reachable(self, reachable: bool) -> dict:
        """Set L3 reachability status."""
        self._l3_reachable = reachable
        if not reachable:
            self._autonomous_mode = True
            logger.warning("L3 unreachable — entering autonomous mode")
        else:
            if self._autonomous_mode:
                self._autonomous_mode = False
                logger.info("L3 restored — exiting autonomous mode")
        return {"success": True, "autonomous_mode": self._autonomous_mode}

    def is_autonomous(self) -> bool:
        return self._autonomous_mode

    def autonomous_operation(self, agent_id: str, action: str, data: dict | None = None) -> dict:
        """Execute an operation in autonomous mode (no L3)."""
        if not self._autonomous_mode:
            return {"success": False, "error": "not in autonomous mode"}
        # Autonomous mode restrictions:
        if action == "execute_task":
            return {"success": True, "note": "task continued in autonomous mode"}
        if action == "cross_review":
            return {"success": True, "note": "cross-review allowed in autonomous mode"}
        if action == "new_intent":
            return {"success": False, "error": "new intents blocked in autonomous mode (L3 required)"}
        if action == "cross_cell":
            return {"success": False, "error": "cross-cell blocked in autonomous mode"}
        return {"success": True}

    # ── Monitor Loop ──

    def _monitor_loop(self) -> None:
        """Background monitor: detect crashes, timeouts, autonomous mode."""
        while self._running:
            time.sleep(FAULT_CHECK_INTERVAL)  # Check every 5s
            try:
                self._check_heartbeats()
            except Exception as e:
                logger.warning("services/fault_tolerance: %s", e)

    def _check_heartbeats(self) -> None:
        now = time.time()
        with self._lock:
            for agent_id, hb in list(self._heartbeats.items()):
                elapsed = now - hb.last_seen
                if elapsed > CRASH_TIMEOUT and hb.status != "crashed":
                    hb.status = "crashed"
                    logger.warning("agent %s crashed (no heartbeat for %.0fs)", agent_id, elapsed)
                    # Trigger recovery
                    threading.Thread(target=self._do_recovery, args=(agent_id,), daemon=True).start()
                elif elapsed > HEARTBEAT_TIMEOUT and hb.status == "alive":
                    hb.status = "unresponsive"
                    logger.warning("agent %s unresponsive (%.0fs)", agent_id, elapsed)

    def _do_recovery(self, agent_id: str) -> None:
        """Background recovery thread."""
        time.sleep(FAULT_RETRY_INTERVAL)
        self.on_agent_crash(agent_id)

    # ── Stats ──

    def stats(self) -> dict:
        with self._lock:
            agents = {}
            for agent_id, hb in self._heartbeats.items():
                agents[agent_id] = {
                    "status": hb.status,
                    "last_seen": hb.last_seen,
                    "has_checkpoint": agent_id in self._checkpoints,
                }
            return {
                "agents": agents,
                "autonomous_mode": self._autonomous_mode,
                "l3_reachable": self._l3_reachable,
                "checkpoints": list(self._checkpoints.keys()),
            }


_service: FaultToleranceService | None = None


def get_service() -> FaultToleranceService:
    global _service
    if _service is None:
        _service = FaultToleranceService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None