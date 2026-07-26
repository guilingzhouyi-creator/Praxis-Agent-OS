"""API handlers for /api/monitor/* endpoints.

Also hosts Token/Monitor/Export handler functions extracted from
api_handlers.py (token_stats, comm_stats, loop_stats, export_*,
network_health) — these are imported by api_handlers.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ── Token / Counter handlers ──

def token_stats(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        c = get_counter()
        window = float(body.get("window", 0)) if body else 0
        if window > 0:
            return {"rate": c.token_rate(window), "summary": c.token_summary()}
        return {"summary": c.token_summary()}
    except Exception as e:
        return {"error": str(e)}


def token_cells(body: dict | None = None) -> dict:
    try:
        from services.central_collector import get_collector
        return {"cells": get_collector().cell_summary()}
    except Exception as e:
        return {"error": str(e)}


def token_global(body: dict | None = None) -> dict:
    try:
        from services.central_collector import get_collector
        return get_collector().global_summary()
    except Exception as e:
        return {"error": str(e)}


# ── Communication handlers ──

def comm_stats(body: dict | None = None) -> dict:
    try:
        from services.comm_monitor import get_monitor
        return get_monitor().stats()
    except Exception as e:
        return {"error": str(e)}


def comm_recent(body: dict | None = None) -> dict:
    try:
        limit = int((body or {}).get("limit", 50))
        from services.comm_monitor import get_monitor
        return {"recent": get_monitor().recent(limit)}
    except Exception as e:
        return {"error": str(e)}


# ── Loop handlers ──

def loop_stats(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        return get_counter().loop_summary()
    except Exception as e:
        return {"error": str(e)}


def loops_recent(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        c = get_counter()
        limit = int((body or {}).get("limit", 20))
        return {"loops": c._all_loops[-limit:]}
    except Exception as e:
        return {"error": str(e)}


# ── Export handlers ──

def export_counter(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        return get_counter().export()
    except Exception as e:
        return {"error": str(e)}


def export_metrics(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        return {"metrics": get_counter().export_metrics()}
    except Exception as e:
        return {"error": str(e)}


# ── Network health ──

def network_health(body: dict | None = None) -> dict:
    try:
        from kernel.net import get_net
        return get_net().health()
    except Exception as e:
        return {"error": str(e)}


# ── Monitor event handlers ──

def handle_monitor_events(body: dict) -> dict:
    """GET /api/monitor/events — query monitor events with filters."""
    try:
        from .monitor_bus import get_bus
        events = get_bus().query(
            type_prefix=body.get("type", ""),
            severity=body.get("severity", ""),
            agent_id=body.get("agent_id", ""),
            cell_id=body.get("cell_id", ""),
            source=body.get("source", ""),
            since=body.get("since", 0.0),
            limit=body.get("limit", 100),
        )
        return {"success": True, "events": events, "count": len(events)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_monitor_stats(body: dict) -> dict:
    """GET /api/monitor/stats — monitor event statistics."""
    try:
        from .monitor_bus import get_bus
        return {"success": True, "stats": get_bus().stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_monitor_stream(body: dict) -> dict:
    """GET /api/monitor/stream — SSE monitor event stream placeholder.

    The actual SSE connection is handled by the HTTP server.
    This handler returns the event queue for polling fallback.
    """
    return handle_monitor_events(body)


def handle_message_gate_list(body: dict) -> dict:
    """GET /api/monitor/gate — list all message gate rules."""
    try:
        from .message_gate import get_gate
        return {"success": True, **get_gate().to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_message_gate_set(body: dict) -> dict:
    """POST /api/monitor/gate — add or update a message gate rule."""
    try:
        from .message_gate import get_gate, MessageGateRule
        rule = MessageGateRule(
            id=body["id"],
            pattern=body.get("pattern", {}),
            action=body.get("action", "block"),
            depends_on=body.get("depends_on", []),
            priority=body.get("priority", 5),
            reason=body.get("reason", ""),
            redirect_target=body.get("redirect_target", ""),
            hold_timeout=body.get("hold_timeout", 3600.0),
        )
        get_gate().add(rule)
        return {"success": True, "rule_id": rule.id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_message_gate_remove(body: dict) -> dict:
    """DELETE /api/monitor/gate/<id> — remove a message gate rule."""
    try:
        rule_id = body.get("id", "")
        if not rule_id:
            return {"success": False, "error": "rule_id is required"}
        ok = get_gate().remove(rule_id)  # noqa: F821
        return {"success": ok}
    except Exception as e:
        return {"success": False, "error": str(e)}
