"""CellWatchdog — per-agent watchdog timer for Cell.

Hardware-style watchdog: each agent slot must be "pet" within a
deadline, or the watchdog fires and escalates through:

  HEALTHY ──(missed pet)──> UNRESPONSIVE ──(timeout)──> CRASHED
     │                          │                         │
     └── pet() resets           └── pet() recovers         └── auto-reboot or NMI

Architecture:
  - One CellWatchdog per Cell, created in Cell.__init__
  - Agent slots registered at boot_agent time
  - Background timer thread runs a tick() at POLL_INTERVAL
  - On timeout: escalates health state, emits MonitorBus event,
    increments PMU watchdog.timeouts counter
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class WatchdogState(Enum):
    HEALTHY = auto()
    UNRESPONSIVE = auto()
    CRASHED = auto()


@dataclass
class WatchdogSlot:
    agent_id: str = ""
    timeout: float = 30.0
    last_pet: float = 0.0
    state: WatchdogState = WatchdogState.HEALTHY
    auto_reboot: bool = True
    consecutive_misses: int = 0
    escalation_count: int = 0


class CellWatchdog:
    """Per-Cell watchdog timer — monitors agent liveness via pet().

    Thread-safe.  Runs a background daemon thread.
    """

    def __init__(
        self,
        cell_id: str,
        poll_interval: float = 5.0,
        default_timeout: float = 30.0,
        unresponsive_escalation: int = 3,
        pmu: Any = None,
    ):
        self.cell_id = cell_id
        self._poll_interval = poll_interval
        self._default_timeout = default_timeout
        self._unresponsive_escalation = unresponsive_escalation
        self._pmu = pmu

        self._slots: dict[str, WatchdogSlot] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None

        # Callbacks — set by Cell to wire escalation actions
        self.on_timeout: Any = None       # fn(agent_id, state) -> None
        self.on_recovery: Any = None      # fn(agent_id) -> None
        self.on_crash: Any = None         # fn(agent_id) -> None

    # ── Slot management ───────────────────────────────────────────

    def register(self, agent_id: str, timeout: float = 0) -> None:
        """Register an agent watchdog slot."""
        with self._lock:
            self._slots[agent_id] = WatchdogSlot(
                agent_id=agent_id,
                timeout=timeout or self._default_timeout,
                last_pet=time.time(),
            )
            logger.debug("watchdog: registered %s (timeout=%ss)", agent_id, timeout or self._default_timeout)

    def unregister(self, agent_id: str) -> None:
        """Remove an agent from watchdog monitoring."""
        with self._lock:
            self._slots.pop(agent_id, None)

    def pet(self, agent_id: str) -> None:
        """Pet the watchdog — resets the timer for this agent.

        If the agent was UNRESPONSIVE, pet() triggers recovery.
        """
        with self._lock:
            slot = self._slots.get(agent_id)
            if slot is None:
                return
            now = time.time()
            was_unresponsive = slot.state == WatchdogState.UNRESPONSIVE
            slot.last_pet = now
            slot.consecutive_misses = 0
            if was_unresponsive:
                slot.state = WatchdogState.HEALTHY
                logger.info("watchdog: %s recovered (was UNRESPONSIVE)", agent_id)
                if self.on_recovery:
                    try:
                        self.on_recovery(agent_id)
                    except Exception as e:
                        logger.warning("watchdog recovery callback failed: %s", e)
            if self._pmu:
                self._pmu.increment("watchdog.pets")

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Start the watchdog timer thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name=f"watchdog-{self.cell_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("watchdog: started for cell %s (poll=%ss)", self.cell_id, self._poll_interval)

    def stop(self) -> None:
        """Stop the watchdog timer thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    # ── Internal timer loop ───────────────────────────────────────

    def _run(self) -> None:
        """Background timer loop — polls slots and escalates on timeout."""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("watchdog tick error: %s", e)
            time.sleep(self._poll_interval)

    def _tick(self) -> None:
        """Check all watchdog slots for timeouts."""
        now = time.time()
        with self._lock:
            for agent_id, slot in list(self._slots.items()):
                elapsed = now - slot.last_pet
                if elapsed < slot.timeout:
                    continue

                # Timeout detected — escalate
                slot.consecutive_misses += 1
                if slot.state == WatchdogState.HEALTHY:
                    slot.state = WatchdogState.UNRESPONSIVE
                    slot.escalation_count += 1
                    logger.warning(
                        "watchdog: %s UNRESPONSIVE (missed pet for %.1fs, timeout=%ss)",
                        agent_id, elapsed, slot.timeout,
                    )
                    if self._pmu:
                        self._pmu.increment("watchdog.timeouts")
                    # Fire on_timeout callback
                    if self.on_timeout:
                        try:
                            self.on_timeout(agent_id, WatchdogState.UNRESPONSIVE)
                        except Exception as e:
                            logger.warning("watchdog timeout callback failed: %s", e)

                elif slot.state == WatchdogState.UNRESPONSIVE:
                    if slot.consecutive_misses >= self._unresponsive_escalation:
                        slot.state = WatchdogState.CRASHED
                        logger.error(
                            "watchdog: %s CRASHED (%d consecutive misses)",
                            agent_id, slot.consecutive_misses,
                        )
                        # Fire on_crash callback (e.g. auto-reboot terminal)
                        if self.on_crash:
                            try:
                                self.on_crash(agent_id)
                            except Exception as e:
                                logger.warning("watchdog crash callback failed: %s", e)

    # ── Query ─────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return watchdog status for all agents."""
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "running": self._running,
                "poll_interval": self._poll_interval,
                "default_timeout": self._default_timeout,
                "slots": {
                    aid: {
                        "state": slot.state.name,
                        "timeout": slot.timeout,
                        "last_pet_ago": round(time.time() - slot.last_pet, 1),
                        "consecutive_misses": slot.consecutive_misses,
                        "auto_reboot": slot.auto_reboot,
                    }
                    for aid, slot in self._slots.items()
                },
            }

    def agent_healthy(self, agent_id: str) -> bool:
        """Check if a specific agent is healthy."""
        with self._lock:
            slot = self._slots.get(agent_id)
            if slot is None:
                return False
            return slot.state == WatchdogState.HEALTHY
