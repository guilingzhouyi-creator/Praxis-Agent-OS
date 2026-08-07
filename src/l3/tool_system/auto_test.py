"""AutoTestGate — post-card background test regression with card feedback.

After a Cell Peer Agent finishes a card with unverified edits, AutoTestGate
(in ``async`` mode) spawns a background thread that runs the project test
suite, parses failure detail from the output, records the result into the
Cell L2 cache, emits an ``auto_test.result`` event (SSE/WS visible), and
queues the result as pending feedback.  The next card produced by the L3A
session consumes the feedback: it is attached to the card columns and the
card is promoted to the highest priority.

Modes (mirror harness.py): off (default) | async.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from typing import Any

from l1.kernel.params.system import (
    HASH_TRUNC_SHORT,
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
    MEMORY_IMPORTANCE_DECISION,
)
from l1.kernel.params.tool import (
    AUTO_TEST_CACHE_KEY,
    AUTO_TEST_DEFAULT_MODE,
    AUTO_TEST_FEEDBACK_MAX,
    AUTO_TEST_MAX_FAILURES,
    AUTO_TEST_MODES,
    AUTO_TEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"mode": None}
_lock = threading.RLock()

# Pending feedback FIFO: oldest first; each entry carries the agent that
# produced it so cardwrite can match the L3A caller when possible.
_feedback: list[dict] = []


# ── Mode switch (mirrors harness.py) ─────────────────────────────────────────


def get_auto_test_mode() -> str:
    """Return the effective auto-test mode (override → config → default)."""
    with _lock:
        override = _state["mode"]
    if override in AUTO_TEST_MODES:
        return override
    try:
        from l1.kernel.discovery import get_tool_config

        static = str(get_tool_config("loop.auto_test", AUTO_TEST_DEFAULT_MODE)).lower()
    except Exception:
        static = AUTO_TEST_DEFAULT_MODE
    return static if static in AUTO_TEST_MODES else AUTO_TEST_DEFAULT_MODE


def set_auto_test(mode: str, source: str = "api") -> dict:
    """Switch the auto-test mode at runtime (off | async).

    Args:
        mode: one of AUTO_TEST_MODES (off / async).
        source: caller identity ("api" / "shell" / ...) for the audit trail.

    Returns:
        dict with success flag and effective mode.
    """
    mode = str(mode or "").lower()
    if mode not in AUTO_TEST_MODES:
        return {"success": False, "error": f"invalid auto-test mode: {mode}", "modes": list(AUTO_TEST_MODES)}
    with _lock:
        _state["mode"] = mode
        _state["source"] = source
    return {"success": True, "mode": mode, "source": source}


def reset_auto_test() -> dict:
    """Clear the runtime override; effective mode returns to static config."""
    with _lock:
        _state["mode"] = None
        _state["source"] = "config"
    return {"success": True, "mode": get_auto_test_mode(), "source": "config"}


def auto_test_status() -> dict:
    """Return the current mode plus pending feedback summary."""
    with _lock:
        source = _state.get("source", "config")
        pending = list(_feedback)
    return {
        "mode": get_auto_test_mode(),
        "source": source,
        "modes": list(AUTO_TEST_MODES),
        "pending_feedback": len(pending),
        "pending_by_agent": _group_by_agent(pending),
    }


def _group_by_agent(entries: list[dict]) -> dict[str, int]:
    grouped: dict[str, int] = {}
    for e in entries:
        aid = e.get("agent_id", "?")
        grouped[aid] = grouped.get(aid, 0) + 1
    return grouped


# ── Pending feedback queue ───────────────────────────────────────────────────


def push_feedback(agent_id: str, payload: dict) -> int:
    """Queue a test result as pending feedback for the next card.

    Returns the number of pending entries after the push.
    """
    entry = dict(payload)
    entry["agent_id"] = agent_id
    entry["queued_at"] = time.time()
    with _lock:
        _feedback.append(entry)
        if len(_feedback) > AUTO_TEST_FEEDBACK_MAX:
            del _feedback[: len(_feedback) - AUTO_TEST_FEEDBACK_MAX]
        return len(_feedback)


def pop_feedback(agent_id: str = "") -> list[dict]:
    """Pop pending feedback: all entries for *agent_id*, else the oldest one.

    Args:
        agent_id: exact-match target; empty string pops the oldest global entry.

    Returns:
        list of popped entries (possibly empty).
    """
    with _lock:
        if not agent_id:
            return [_feedback.pop(0)] if _feedback else []
        matched = [e for e in _feedback if e.get("agent_id") == agent_id]
        if not matched:
            return []
        for e in matched:
            _feedback.remove(e)
        return matched


def pending_feedback() -> list[dict]:
    """Return a copy of all pending feedback entries (oldest first)."""
    with _lock:
        return list(_feedback)


def clear_feedback() -> int:
    """Drop all pending feedback. Returns the number of cleared entries."""
    with _lock:
        n = len(_feedback)
        _feedback.clear()
        return n


# ── Background execution ─────────────────────────────────────────────────────


def maybe_trigger(agent_id: str, cell_id: str, task: str, unverified: list[str], card_id: str = "") -> bool:
    """Spawn a background test run when enabled and edits are pending.

    Args:
        agent_id: the Peer Agent that finished the card.
        cell_id: its Cell (result cache scope).
        task: the finished card task text (cache key + payload context).
        unverified: edited paths with no verification command seen.
        card_id: optional card id for the L3A session task table.

    Returns:
        True when a background run was spawned, False otherwise.
    """
    if get_auto_test_mode() != "async":
        return False
    if not unverified:
        return False
    try:
        thread = threading.Thread(
            target=_run,
            args=(agent_id, cell_id, task, list(unverified), card_id or ""),
            daemon=True,
            name=f"auto-test-{agent_id[:12]}",
        )
        thread.start()
        return True
    except Exception as e:
        logger.warning("auto_test: spawn failed: %s", e)
        return False


def _run(agent_id: str, cell_id: str, task: str, edited_paths: list[str], card_id: str) -> None:
    """Background body: execute the test suite and distribute the result."""
    try:
        t0 = time.time()
        res = _execute_tests()
        payload = {
            "agent_id": agent_id,
            "cell_id": cell_id,
            "task": task[:LOG_TRUNC_200],
            "card_id": card_id,
            "passed": res.get("passed", False),
            "command": res.get("command", ""),
            "failures": res.get("failures", []),
            "elapsed": round(time.time() - t0, 2),
            "edited": edited_paths[:10],
            "at": time.time(),
        }
        _distribute_result(agent_id, cell_id, task, payload)
    except Exception as e:
        logger.warning("auto_test run failed: %s", e)


def _distribute_result(agent_id: str, cell_id: str, task: str, payload: dict) -> None:
    """Write the Cell L2 cache, emit events, and queue card feedback."""
    key = _cache_key(task)
    try:
        from l3.cell import get_cell as _get_cell

        cell = _get_cell(cell_id)
        if cell is not None:
            summary = (
                f"PASS [{agent_id}]" if payload["passed"] else f"FAIL [{agent_id}] {len(payload['failures'])} failed"
            )
            cell.cache.inject(
                key=key,
                value=payload,
                summary=summary[:LOG_TRUNC_200],
                agent_id=agent_id,
                entry_type="auto_test",
                importance=MEMORY_IMPORTANCE_DECISION,
            )
    except Exception as e:
        logger.debug("auto_test: cell cache inject failed: %s", e)
    try:
        from l1.kernel.event import get_bus as _get_bus

        _get_bus().emit_event("auto_test.result", data=payload, source=agent_id)
    except Exception as e:
        logger.debug("auto_test: event emit failed: %s", e)
    try:
        from l3.bus.monitor_bus import MonitorEvent as _MonitorEvent
        from l3.bus.monitor_bus import get_bus as _MB

        _MB().emit(
            _MonitorEvent(
                type="auto_test.result",
                source="auto_test",
                severity="info" if payload["passed"] else "warning",
                message=f"{agent_id} tests {'passed' if payload['passed'] else 'failed'} "
                f"({len(payload['failures'])} failures)",
                agent_id=agent_id,
                cell_id=cell_id,
                data=payload,
            )
        )
    except Exception as e:
        logger.debug("auto_test: monitor emit failed: %s", e)
    push_feedback(agent_id, payload)


def _cache_key(task: str) -> str:
    digest = hashlib.sha256(task.encode()).hexdigest()[:HASH_TRUNC_SHORT]
    return f"{AUTO_TEST_CACHE_KEY}:{digest}"


# ── Test execution + failure parsing ─────────────────────────────────────────


def _execute_tests() -> dict:
    """Run the project test suite via the detectors; parse failure detail.

    Returns:
        {"passed": bool, "command": str, "failures": [str], "output": str}
    """
    from l3.tool_system._build import _get_test_detectors

    from l1.kernel.platform import run_args

    for cmd in _get_test_detectors():
        try:
            r = run_args(list(cmd), timeout=AUTO_TEST_TIMEOUT)
            output = f"{r.stdout}\n{r.stderr}"[:LOG_TRUNC_2000]
            failures = parse_pytest_failures(output)
            return {
                "passed": r.returncode == 0 and not failures,
                "command": " ".join(cmd),
                "failures": failures,
                "output": output,
            }
        except Exception:
            continue
    return {"passed": False, "command": "", "failures": [], "output": "no supported test framework found"}


def parse_pytest_failures(output: str) -> list[str]:
    """Extract FAILED/ERROR test ids from pytest output (dedup, capped).

    Matches the pytest summary lines ``FAILED path::test - reason`` and
    ``ERROR path::test``.
    """
    names: set[str] = set()
    for m in re.finditer(r"^(?:FAILED|ERROR)\s+(.+?)(?:\s*-\s*|$)", output or "", re.MULTILINE):
        name = m.group(1).strip()
        if name:
            names.add(name)
    return sorted(names)[:AUTO_TEST_MAX_FAILURES]
