"""CronScheduler — cron-style repeatable card dispatch.

Design:
  - Maps cron expressions to Card definitions in praxis.yaml → schedules:
  - Internal loop checks every 60s, dispatches cards when cron matches
  - Supports: "*/5 * * * *" (every 5 min), "0 3 * * *" (daily 3am)
  - Uses CardRegistry.submit() to inject scheduled cards
  - Non-blocking: runs in daemon thread

Usage:
  praxis.yaml:
    schedules:
      nightly-cleanup:
        cron: "0 3 * * *"
        intent: "Clean up temp files and old cache"
        domain: "ops"
        priority: 3
      health-check:
        cron: "*/30 * * * *"
        intent: "Run system health check"
        domain: "ops"
        priority: 5
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from kernel.params import CRON_CHECK_INTERVAL

logger = logging.getLogger(__name__)

# Simple cron field parser — supports: *, */N, N,N, N
_CRON_PATTERN = re.compile(
    r"^(\*(\/\d+)?|\d+(\/\d+)?(,\d+)*)\s+"   # minute
    r"(\*(\/\d+)?|\d+(\/\d+)?(,\d+)*)\s+"    # hour
    r"(\*(\/\d+)?|\d+(\/\d+)?(,\d+)*)\s+"    # day of month
    r"(\*(\/\d+)?|\d+(\/\d+)?(,\d+)*)\s+"    # month
    r"(\*(\/\d+)?|\d+(\/\d+)?(,\d+)*)$"      # day of week
)


def _match_cron_field(field: str, value: int) -> bool:
    """Check if a value matches a cron field expression."""
    if field == "*":
        return True
    for part in field.split(","):
        if "/" in part:
            base, step = part.split("/")
            base_val = 0 if base == "*" else int(base)
            step_val = int(step)
            if (value - base_val) % step_val == 0 and value >= base_val:
                return True
        else:
            if int(part) == value:
                return True
    return False


def _cron_matches(expression: str, now: time.struct_time | None = None) -> bool:
    """Check if a cron expression matches the current time."""
    parts = expression.strip().split()
    if len(parts) != 5:
        return False
    t = now or time.localtime()
    return (
        _match_cron_field(parts[0], t.tm_min) and
        _match_cron_field(parts[1], t.tm_hour) and
        _match_cron_field(parts[2], t.tm_mday) and
        _match_cron_field(parts[3], t.tm_mon) and
        _match_cron_field(parts[4], t.tm_wday)
    )


def validate_cron(expression: str) -> bool:
    """Validate a cron expression format."""
    return bool(_CRON_PATTERN.match(expression.strip()))


class CronScheduler:
    """Cron-style scheduler that dispatches cards on schedule."""

    def __init__(self):
        self._entries: list[dict] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_checked: dict[str, float] = {}  # entry_id → last dispatch time
        self._load_config()

    def _load_config(self) -> None:
        """Load cron entries from praxis.yaml → schedules: section."""
        try:
            from services.config_loader import load as load_config
            cfg = load_config()
            schedules = cfg.get("schedules", {})
            if isinstance(schedules, dict):
                for name, info in schedules.items():
                    if isinstance(info, dict) and info.get("cron") and info.get("intent"):
                        cron_expr = info["cron"].strip()
                        if validate_cron(cron_expr):
                            self._entries.append({
                                "id": name,
                                "cron": cron_expr,
                                "intent": info["intent"],
                                "domain": info.get("domain", ""),
                                "priority": info.get("priority", 5),
                                "cell_id": info.get("cell_id", "cell-1"),
                            })
                            logger.info("cron: loaded '%s' → %s", name, cron_expr)
        except Exception as e:
            logger.warning("cron: config load failed: %s", e)

    def add(self, entry_id: str, cron: str, intent: str,
            domain: str = "", priority: int = 5,
            cell_id: str = "cell-1") -> dict:
        """Register a cron entry programmatically."""
        if not validate_cron(cron):
            return {"success": False, "error": f"invalid cron expression: {cron}"}
        entry = {
            "id": entry_id,
            "cron": cron,
            "intent": intent,
            "domain": domain,
            "priority": priority,
            "cell_id": cell_id,
        }
        with self._lock:
            # Replace if exists
            for i, e in enumerate(self._entries):
                if e["id"] == entry_id:
                    self._entries[i] = entry
                    break
            else:
                self._entries.append(entry)
        logger.info("cron: added '%s' → %s", entry_id, cron)
        return {"success": True, "id": entry_id, "cron": cron}

    def remove(self, entry_id: str) -> dict:
        """Remove a cron entry."""
        with self._lock:
            self._entries = [e for e in self._entries if e["id"] != entry_id]
        return {"success": True, "id": entry_id}

    def list(self) -> list[dict]:
        """List all cron entries."""
        with self._lock:
            return [dict(e) for e in self._entries]

    def start(self) -> None:
        """Start the scheduler loop in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("cron: scheduler started")

    def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        logger.info("cron: scheduler stopped")

    def _loop(self) -> None:
        """Main scheduler loop — checks every 60s."""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("cron: tick error: %s", e)
            time.sleep(CRON_CHECK_INTERVAL)

    def _tick(self) -> None:
        """Check all entries and dispatch matching ones."""
        now = time.time()
        now_struct = time.localtime(now)
        with self._lock:
            for entry in self._entries:
                eid = entry["id"]
                last = self._last_checked.get(eid, 0)
                # Prevent double-dispatch within same minute
                if now - last < 60:
                    continue
                if _cron_matches(entry["cron"], now_struct):
                    self._last_checked[eid] = now
                    self._dispatch(entry)

    def _dispatch(self, entry: dict) -> None:
        """Submit a card for a cron entry."""
        try:
            from .card_registry import get_registry
            reg = get_registry()
            cid = reg.submit(
                intent=entry["intent"],
                domain=entry.get("domain", ""),
                priority=entry.get("priority", 5),
                source="cron",
            )
            logger.info("cron: dispatched '%s' → card_id=%s", entry["id"], cid)
        except Exception as e:
            logger.error("cron: dispatch '%s' failed: %s", entry["id"], e)


_scheduler: CronScheduler | None = None


def get_scheduler() -> CronScheduler:
    """Get singleton CronScheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = CronScheduler()
    return _scheduler


def reset_scheduler() -> None:
    """Reset singleton (for testing)."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
    _scheduler = None
