"""Lifecycle — unified system state machine and persistent registry.

Zero upper-layer dependencies (kernel-level). Tracks install, boot, shutdown
phases with a finite state machine and a persistent JSON record.

State transitions:
  HALTED ──[install()]──→ INSTALLING ──→ BOOTING ──→ ACTIVE
  HALTED ──[boot()]─────→ BOOTING ──[success]──→ ACTIVE
  BOOTING ──[fail]──────→ CRASHED
  ACTIVE ──[shutdown()]─→ DRAINING ──→ HALTED
  CRASHED ──[boot()]────→ BOOTING
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from .params.system import LIFECYCLE_STATE_FILE

logger = logging.getLogger(__name__)

_LIFECYCLE_FILE = LIFECYCLE_STATE_FILE


class LifecycleState(Enum):
    """LifecycleState — enum of HALTED, INSTALLING, BOOTING, ACTIVE...."""
    HALTED = "halted"
    INSTALLING = "installing"
    BOOTING = "booting"
    ACTIVE = "active"
    DRAINING = "draining"
    CRASHED = "crashed"


_VALID_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.HALTED: {LifecycleState.INSTALLING, LifecycleState.BOOTING},
    LifecycleState.INSTALLING: {LifecycleState.BOOTING, LifecycleState.CRASHED},
    LifecycleState.BOOTING: {LifecycleState.ACTIVE, LifecycleState.CRASHED},
    LifecycleState.ACTIVE: {LifecycleState.DRAINING, LifecycleState.CRASHED},
    LifecycleState.DRAINING: {LifecycleState.HALTED, LifecycleState.CRASHED},
    LifecycleState.CRASHED: {LifecycleState.BOOTING},
}


@dataclass
class LifecycleRecord:
    """LifecycleRecord — lifecycle record record (install_version, schema_version, last_boot, last_boot_success, last_shutdown)."""
    install_version: int = 0
    schema_version: str = ""
    last_boot: str = ""
    last_boot_success: bool = False
    last_shutdown: str = ""
    last_shutdown_clean: bool = False
    boot_count: int = 0
    lifecycle_state: str = LifecycleState.HALTED.value


class LifecycleRegistry:
    """Persistent lifecycle state tracker backed by JSON file."""

    def __init__(self, persist_path: str = _LIFECYCLE_FILE):
        self._path = persist_path
        self._lock = threading.RLock()
        self._record = LifecycleRecord()
        self._state = LifecycleState.HALTED
        self._loaded = False

    def load(self) -> LifecycleRecord:
        with self._lock:
            if self._loaded:
                return self._record
            self._loaded = True
            if not os.path.exists(self._path):
                return self._record
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                for key, val in data.items():
                    if hasattr(self._record, key):
                        setattr(self._record, key, val)
                if self._record.lifecycle_state:
                    try:
                        self._state = LifecycleState(self._record.lifecycle_state)
                    except ValueError:
                        self._state = LifecycleState.HALTED
            except Exception as e:
                logger.warning("lifecycle: load failed: %s", e)
            return self._record

    def save(self) -> None:
        with self._lock:
            self._record.lifecycle_state = self._state.value
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._record.__dict__, f, indent=2, default=str)
                os.replace(tmp, self._path)
            except Exception as e:
                logger.warning("lifecycle: save failed: %s", e)

    def state(self) -> LifecycleState:
        with self._lock:
            return self._state

    def transition(self, target: LifecycleState) -> bool:
        with self._lock:
            current = self._state
            allowed = _VALID_TRANSITIONS.get(current, set())
            if target not in allowed:
                logger.warning("lifecycle: invalid transition %s → %s", current.value, target.value)
                return False
            self._state = target
            self._record.lifecycle_state = target.value
            logger.info("lifecycle: %s → %s", current.value, target.value)
        self.save()
        return True

    def should_install(self) -> bool:
        rec = self.load()
        if rec.install_version == 0:
            return True
        from l1.kernel.migration import SCHEMA_VERSION
        if rec.schema_version != SCHEMA_VERSION:
            return True
        # Unclean shutdown → reinstall
        if rec.last_shutdown:
            return not rec.last_shutdown_clean
        # Booted but never cleanly shut down (crash without atexit) → reinstall
        return rec.boot_count > 0

    def record_boot_success(self) -> None:
        self.load()
        self._record.boot_count += 1
        self._record.last_boot = datetime.now(UTC).isoformat()
        self._record.last_boot_success = True
        self.save()

    def record_boot_failure(self) -> None:
        self.load()
        self._record.last_boot = datetime.now(UTC).isoformat()
        self._record.last_boot_success = False
        self.save()

    def record_shutdown(self, clean: bool = True) -> None:
        self.load()
        self._record.last_shutdown = datetime.now(UTC).isoformat()
        self._record.last_shutdown_clean = clean
        self.save()


# ── Module-level singleton ──

_lifecycle: LifecycleRegistry | None = None
_lifecycle_lock = threading.Lock()


def get_lifecycle() -> LifecycleRegistry:
    """Get the system lifecycle state machine singleton."""
    global _lifecycle
    if _lifecycle is None:
        with _lifecycle_lock:
            if _lifecycle is None:
                _lifecycle = LifecycleRegistry()
    return _lifecycle


def reset_lifecycle() -> None:
    global _lifecycle
    _lifecycle = None


def state() -> LifecycleState:
    return get_lifecycle().state()


def transition(target: LifecycleState) -> bool:
    """Apply a lifecycle state transition (validate and persist)."""
    return get_lifecycle().transition(target)
