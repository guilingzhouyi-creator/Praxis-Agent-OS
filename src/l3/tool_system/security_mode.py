"""Security mode runtime state — productive vs security-test system posture.

The system posture is a combination of two axes:
  - security.mode: productive (default, normal build) | security-test (attack)
  - harness.mode:  governed / semi / minimal (execution rigor, see harness.py)

``get_posture()`` returns the combined classification:
  - productive posture: security.mode == productive (any harness) — the
    execution layer is never granted attack capability;
  - attack posture:     security.mode == security-test (any harness);
  - full_power:         attack posture AND detection-bypass confirmed.

Switching to security-test requires an explicit detection-bypass
confirmation (``confirm_risk=True``) — the caller asserts the target is an
authorized attack target. The safety bottom line (constitution + gatechain +
sandbox + reference-channel recording) is enforced by the pipeline itself and
can never be disabled through this module.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.system import (
    SECURITY_MODE_DEFAULT,
    SECURITY_MODE_PRODUCTIVE,
    SECURITY_MODE_TEST,
    SECURITY_MODES,
)

_state: dict[str, Any] = {"mode": None, "confirmed": False}
_lock = threading.RLock()

BOTTOM_LINE = "constitution + gatechain + sandbox + reference-channel recording"

# Bounded notification history — bypass-detection warnings and mode changes
# stay queryable by frontends via the GET /api/v2/security/mode/notifications
# endpoint (pull channel) in addition to the SSE push.
_NOTIFICATION_MAX = 20
_notifications: deque[dict] = deque(maxlen=_NOTIFICATION_MAX)


def get_security_mode() -> str:
    """Return the effective security mode (override → config → default)."""
    with _lock:
        override = _state["mode"]
    if override in SECURITY_MODES:
        return override
    static = str(get_tool_config("security_mode", SECURITY_MODE_DEFAULT)).lower()
    return static if static in SECURITY_MODES else SECURITY_MODE_DEFAULT


def set_security_mode(mode: str, confirmed: bool = False, source: str = "api") -> dict:
    """Switch the system security posture at runtime.

    Args:
        mode: one of SECURITY_MODES (productive | security-test).
        confirmed: explicit detection-bypass confirmation; REQUIRED for
            ``security-test`` — the caller asserts the target is authorized.
        source: caller identity ("api" / "shell" / ...) for the audit trail.

    Returns:
        dict with success flag, effective mode, posture classification and a
        warning payload when switching into attack posture.
    """
    mode = str(mode or "").lower()
    if mode not in SECURITY_MODES:
        return {"success": False, "error": f"invalid security mode: {mode}",
                "modes": list(SECURITY_MODES)}
    if mode == SECURITY_MODE_TEST and not confirmed:
        warning = {
            "code": "SECURITY_TEST_CONFIRM_REQUIRED",
            "message": "attack posture requires explicit bypass confirmation",
            "classification": "attack",
            "bottom_line": BOTTOM_LINE,
            "mode": mode,
            "source": source,
        }
        _emit_mode_event("security_mode_warning", warning, source)
        ingest_security_metric("security.bypass.denied", tags={"mode": mode, "source": source})
        return {
            "success": False,
            "error": "security-test mode requires detection-bypass confirmation "
                     "(confirm_risk=true): the execution layer will be granted "
                     "full-power attack authorization for offensive tools/skills "
                     "on authorized targets. Safety bottom line "
                     f"({BOTTOM_LINE}) stays enforced.",
            "modes": list(SECURITY_MODES),
            "warning": warning,
        }
    with _lock:
        _state["mode"] = mode
        _state["confirmed"] = bool(confirmed)
        _state["source"] = source
    result = {
        "success": True,
        "mode": mode,
        "source": source,
        "posture": get_posture(),
    }
    # Phase B: full_power state gauge (1.0 when attack+confirmed, else 0.0)
    # plus the bypass confirmation distribution counters.
    ingest_security_metric(
        "security.posture.full_power",
        value=1.0 if result["posture"].get("full_power") else 0.0,
        tags={"mode": mode},
    )
    ingest_security_metric(
        "security.bypass.confirmed" if confirmed else "security.bypass.denied",
        tags={"mode": mode, "source": source},
    )
    _emit_mode_event(
        "security_mode_change",
        {"mode": mode, "confirmed": bool(confirmed), "posture": result["posture"], "source": source},
        source,
    )
    return result


def _emit_mode_event(event_type: str, data: dict, source: str) -> None:
    """Record + emit a security-mode event (frontend-notifiable, RC-metric).

    ``security_mode_warning`` fires when a detection-bypass confirmation is
    required; ``security_mode_change`` fires after a successful switch. Each
    entry is appended to the bounded notification history (queryable via
    ``security_notifications()`` / the API endpoint), broadcast on the
    EventBus for the SSE bridge, and ingested into StatsCenter as a
    ``security.mode.*`` metric so the security posture is observable in the
    RC/StatsCenter time series.
    """
    entry = {
        "type": event_type,
        "data": data,
        "source": source or "security_mode",
        "ts": time.time(),
    }
    with _lock:
        _notifications.append(entry)
    try:
        from l1.kernel.event import get_bus

        get_bus().emit_event(event_type, data=data, source=source or "security_mode")
    except Exception:
        # Notification is best-effort — never break the mode switch.
        pass
    try:
        # Phase D: security events also land in the ReferenceChannel
        # (audit/training JSONL) so the security posture is queryable through
        # the RC reference source alongside EventBus and StatsCenter.
        from l3.bus.reference_channel import get_rc

        get_rc().event(event_type, data=data, source=source or "security_mode")
    except Exception:
        # Reference write is best-effort — never break the mode switch.
        pass
    try:
        # P0: bridge to StatsCenter so RC time series cover the security
        # posture — metric names follow the security.* namespace.
        from l3.services.stats_center import MetricPoint, get_center

        metric = "security.mode.change" if event_type == "security_mode_change" else "security.mode.warning"
        get_center().ingest(
            MetricPoint(
                name=metric,
                value=1.0,
                tags={
                    "source": "security_mode",
                    "mode": str(data.get("mode", "")),
                    "confirmed": str(bool(data.get("confirmed", False))).lower(),
                },
                timestamp=time.time(),
                metric_type="counter",
            )
        )
    except Exception:
        # Metric bridge is best-effort — never break the mode switch.
        pass


def ingest_security_metric(name: str, value: float = 1.0, tags: dict | None = None) -> None:
    """Best-effort StatsCenter ingest for security.* counters (P1).

    Shared by the posture gate, GateChain G4 bypass, warrant issuance and
    attack-team activation hooks so every security-relevant event lands in
    the RC/StatsCenter time series. Never raises — observability must not
    break the protected path.
    """
    try:
        from l3.services.stats_center import MetricPoint, get_center

        get_center().ingest(
            MetricPoint(
                name=name,
                value=float(value),
                tags={"source": "security", **(tags or {})},
                timestamp=time.time(),
                metric_type="counter",
            )
        )
    except Exception:
        pass


def security_notifications(limit: int = 0, event_type: str = "") -> list[dict]:
    """Return recent security-mode notifications (newest first).

    Args:
        limit: Max entries (0 = all buffered).
        event_type: Optional filter ("security_mode_warning" /
            "security_mode_change").

    Exposed to frontends via GET /api/v2/security/mode/notifications so the
    latest bypass-detection warning can be pulled even after the SSE push was
    missed.
    """
    with _lock:
        items = list(_notifications)
    items.reverse()  # newest first
    if event_type:
        items = [i for i in items if i.get("type") == event_type]
    if limit > 0:
        items = items[:limit]
    return items


def reset_security_mode() -> dict:
    """Clear the runtime override; effective posture returns to static config."""
    with _lock:
        _state["mode"] = None
        _state["confirmed"] = False
        _state["source"] = "config"
    return {"success": True, "mode": get_security_mode(), "source": "config"}


def get_posture() -> dict:
    """Return the combined system posture (security × harness).

    Classification: ``productive`` | ``attack``. ``full_power`` is True only
    when attack-classified AND the detection-bypass was explicitly confirmed —
    the single flag every execution-layer gate reads before granting attack
    capability.
    """
    from l3.tool_system.harness import get_harness_mode

    security_mode = get_security_mode()
    harness_mode = get_harness_mode()
    with _lock:
        confirmed = bool(_state.get("confirmed"))
    classification = SECURITY_MODE_TEST if security_mode == SECURITY_MODE_TEST else SECURITY_MODE_PRODUCTIVE
    return {
        "security_mode": security_mode,
        "harness_mode": harness_mode,
        "classification": classification,
        "full_power": classification == SECURITY_MODE_TEST and confirmed,
        "confirmed": confirmed,
        "bottom_line": BOTTOM_LINE,
    }


def security_status() -> dict:
    """Return the current security posture plus the switchable matrix."""
    return {"success": True, "posture": get_posture(), "modes": list(SECURITY_MODES)}
