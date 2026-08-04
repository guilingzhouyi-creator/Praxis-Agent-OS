"""SSE Bridge — EventBus over HTTP (Server-Sent Events)

Push kernel EventBus events in real-time to HTTP clients.
The frontend subscribes via EventSource /api/events.

Usage:
  GET /api/events — SSE stream, continuously pushes events
  GET /api/events?type=error_log — filter by event type
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from l1.kernel.params.api import SSE_QUEUE_MAXSIZE

logger = logging.getLogger(__name__)

# SSE client registry
_sse_clients: list[dict] = []  # [{"queue": Queue, "types": set, "id": str}]
_sse_lock = threading.RLock()
_client_counter = 0
_HAS_LISTENER = False  # guard: register EventBus listener only once


def subscribe(event_types: set[str] | None = None) -> dict:
    """Register an SSE client; returns client ID and message queue."""
    global _client_counter, _HAS_LISTENER
    q: queue.Queue = queue.Queue(maxsize=SSE_QUEUE_MAXSIZE)
    with _sse_lock:
        _client_counter += 1
        client_id = f"sse-{_client_counter}"
        _sse_clients.append({
            "id": client_id,
            "queue": q,
            "types": event_types or set(),
        })
        # Register EventBus listener exactly once, not per-client
        if not _HAS_LISTENER:
            _HAS_LISTENER = True
            try:
                from l1.kernel import get_event_bus
                bus = get_event_bus()
                bus.on_event("sse_bridge", lambda sig: _broadcast(
                    sig.type.name if hasattr(sig.type, 'name') else str(sig.type),
                    sig.data if hasattr(sig, 'data') else {},
                ))
            except Exception as e:
                logger.warning("sse_bridge: event bus subscribe: %s", e)
    return {"client_id": client_id, "queue": q}


def _broadcast(event_type: str, data: Any) -> None:
    """Push an event to matching SSE clients."""
    with _sse_lock:
        dead: list[str] = []
        for client in _sse_clients:
            if client["types"] and event_type not in client["types"]:
                continue
            try:
                client["queue"].put_nowait({
                    "type": event_type,
                    "data": data,
                    "timestamp": time.time(),
                })
            except queue.Full:
                dead.append(client["id"])
        for cid in dead:
            _sse_clients[:] = [c for c in _sse_clients if c["id"] != cid]


def unsubscribe(client_id: str) -> None:
    """Remove an SSE client."""
    with _sse_lock:
        _sse_clients[:] = [c for c in _sse_clients if c["id"] != client_id]


def push_event(event_type: str, data: Any) -> None:
    """External entry: push an event to EventBus (automatically broadcasts to SSE)."""
    try:
        from l1.kernel import emit_event
        emit_event(event_type, data, source="sse_bridge")
    except Exception:
        logger.debug("sse_bridge: kernel emit failed")
    _broadcast(event_type, data)


# Global activation flag
_ACTIVE = False


def ensure_active() -> None:
    """Ensure the SSE bridge is activated (auto-subscribes to EventBus)."""
    global _ACTIVE
    if _ACTIVE:
        return
    try:
        from l1.kernel import get_event_bus
        bus = get_event_bus()
        # Register wildcard listener: broadcast all events
        bus.on_any(lambda sig: _broadcast(
            sig.type.name if hasattr(sig.type, 'name') else str(sig.type),
            sig.data if hasattr(sig, 'data') else {},
        ))
        _ACTIVE = True
        logger.info("sse_bridge: active, broadcasting all EventBus events")
        # Subscribe StatsCenter live metrics to SSE bridge
        try:
            from l3.services.stats_center import get_center
            center = get_center()
            center.subscribe_sse(lambda event: _broadcast(
                event.get("type", "stats.metric"),
                event,
            ))
            logger.info("sse_bridge: subscribed to StatsCenter live metrics")
        except Exception as e:
            logger.warning("sse_bridge: stats center subscribe failed: %s", e)
    except Exception as e:
        logger.warning("sse_bridge: activation failed: %s", e)


# ══════════════════════════════════════════════════════════════════════
# API Handler
# ══════════════════════════════════════════════════════════════════════
#
# Note: SSE handler requires special handling in the HTTP server (long-lived connection).
# In api_gateway.py's do_GET, special-case the check for this.


def handle_sse(body: dict | None = None) -> dict:
    """GET /api/events — Special handler for SSE streams.

    Returns a special dict marker; when the HTTP server sees this marker,
    it switches to SSE mode (long-lived connection + text/event-stream).
    """
    return {"_sse": True, "message": "SSE stream — use EventSource /api/events"}


# ── Routes ──
# Routes are consolidated in l4/api/api_endpoints.py (ENDPOINT_MANIFEST); no duplicate list maintained here.
