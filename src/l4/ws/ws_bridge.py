"""WebSocket bridge — bidirectional realtime channel (mirrors sse_bridge).

Complements the one-way SSE bridge: clients get a persistent socket to
subscribe to EventBus events AND issue RPC-style requests whose results
are pushed back over the same connection.

Client message protocol:
  {"type": "subscribe",   "events": ["card.pending", ...]}
  {"type": "unsubscribe", "events": ["card.pending", ...]}
  {"type": "rpc",         "method": "/api/v2/card/submit", "params": {...}}

Server message protocol:
  {"type": "event",     "event": "card.pending", "data": {...}, "timestamp": ...}
  {"type": "rpc.result","method": ..., "data": {...}}
  {"type": "error",     "message": ...}

Server runs on its own port (API_WS_PORT) via websockets.sync, so the
synchronous HTTP gateway needs no upgrade handling.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from l1.kernel.params.api import API_WS_PORT, API_GATEWAY_HOST
from l1.kernel.ports import WebSocketPort
from websockets.sync.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# ── Client registry ──
_ws_clients: list[dict] = []  # [{"conn", "types": set, "id": str}]
_ws_lock = threading.RLock()
_ws_counter = 0
_HAS_LISTENER = False


class WsBridgePort(WebSocketPort):
    """WebSocketPort adapter — connection-handle model over the shared registry.

    ``upgrade(conn)`` registers an accepted socket and returns a per-client
    handle (explicit connection model); recv/send/close operate only on that
    handle.  broadcast() pushes to all subscribed clients.  The standalone
    server (start_server) and the port share the same registry.
    """

    def upgrade(self, request: Any) -> Any:
        global _ws_counter
        _register_event_listener()
        with _ws_lock:
            _ws_counter += 1
            handle = {"conn": request, "types": set(), "id": f"ws-{_ws_counter}"}
            _ws_clients.append(handle)
        return handle

    def recv(self, conn: Any) -> dict | None:
        raw = conn["conn"].recv()
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def send(self, conn: Any, msg: dict) -> bool:
        try:
            conn["conn"].send(json.dumps(msg, default=str))
            return True
        except Exception:
            return False

    def close(self, conn: Any) -> None:
        with _ws_lock:
            _ws_clients[:] = [c for c in _ws_clients if c["id"] != conn["id"]]
        try:
            conn["conn"].close()
        except Exception:
            pass

    def broadcast(self, event: str, data: dict) -> None:
        _broadcast(event, data)


def _register_event_listener() -> None:
    """Register the EventBus wildcard listener exactly once."""
    global _HAS_LISTENER
    if _HAS_LISTENER:
        return
    _HAS_LISTENER = True
    try:
        from l1.kernel import get_event_bus

        bus = get_event_bus()
        bus.on_any(lambda sig: _broadcast(
            sig.type.name if hasattr(sig.type, "name") else str(sig.type),
            sig.data if hasattr(sig, "data") else {},
        ))
    except Exception as e:
        logger.warning("ws_bridge: event bus subscribe: %s", e)


def _broadcast(event_type: str, data: Any) -> None:
    """Push an event to matching clients."""
    with _ws_lock:
        dead: list[str] = []
        payload = json.dumps({
            "type": "event", "event": event_type, "data": data,
            "timestamp": time.time(),
        }, default=str)
        for client in _ws_clients:
            if client["types"] and event_type not in client["types"]:
                continue
            try:
                client["conn"].send(payload)
            except Exception:
                dead.append(client["id"])
        if dead:
            _ws_clients[:] = [c for c in _ws_clients if c["id"] not in dead]


def _send(client: dict, msg: dict) -> None:
    try:
        client["conn"].send(json.dumps(msg, default=str))
    except Exception:
        pass


def _import_handler(ref: str):
    """Import a handler function from a ``module.path.func`` reference."""
    mod_path, _, func_name = ref.rpartition(".")
    if not mod_path:
        raise ImportError(f"bad handler ref: {ref}")
    import importlib

    mod = importlib.import_module(mod_path)
    return getattr(mod, func_name)


def _resolve_rpc(method: str, params: dict) -> dict:
    """Route an RPC method (full API path) to its POST handler."""
    from l4.api.api_routes import API_ROUTES

    for m, p, h, _ in API_ROUTES:
        if p == method and m == "POST":
            if not h.startswith("l4."):
                return {"success": False, "error": f"rpc not available for {method}"}
            try:
                handler = _import_handler(h)
            except Exception as e:
                return {"success": False, "error": f"handler import failed: {e}"}
            try:
                return handler(params or {})
            except Exception as e:
                return {"success": False, "error": f"handler error: {e}"}
    return {"success": False, "error": f"unknown rpc method: {method}"}


def handle_client(conn: Any) -> None:
    """Per-connection loop: register, then dispatch client messages."""
    global _ws_counter
    _register_event_listener()
    with _ws_lock:
        _ws_counter += 1
        client = {"conn": conn, "types": set(), "id": f"ws-{_ws_counter}"}
        _ws_clients.append(client)
    try:
        while True:
            raw = conn.recv()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                _send(client, {"type": "error", "message": "invalid JSON"})
                continue
            mtype = msg.get("type")
            if mtype == "subscribe":
                client["types"].update(msg.get("events") or [])
            elif mtype == "unsubscribe":
                for e in msg.get("events") or []:
                    client["types"].discard(e)
            elif mtype == "rpc":
                method = str(msg.get("method") or "")
                params = msg.get("params") or {}
                result = _resolve_rpc(method, params)
                _send(client, {"type": "rpc.result", "method": method, "data": result})
            else:
                _send(client, {"type": "error", "message": f"unknown message type: {mtype}"})
    except ConnectionClosed:
        pass
    except Exception as e:
        logger.debug("ws_bridge: client loop error: %s", e)
    finally:
        with _ws_lock:
            _ws_clients[:] = [c for c in _ws_clients if c["id"] != client["id"]]


def start_server(host: str = "", port: int = 0) -> threading.Thread:
    """Start the WS bridge server on a background daemon thread.

    Self-registers the ``ws`` port (WebSocketPort adapter) on first start so
    callers can reach the bridge through ``get_port("ws")``.
    """
    host = host or API_GATEWAY_HOST
    port = port or API_WS_PORT
    try:
        from l1.kernel.ports import register_port
        register_port("ws", WsBridgePort())
    except Exception:
        logger.debug("ws_bridge: port self-registration skipped")

    def _run() -> None:
        try:
            with ws_serve(handle_client, host, port) as server:
                logger.info("ws_bridge: listening on ws://%s:%d", host, port)
                server.serve_forever()
        except Exception as e:
            logger.warning("ws_bridge: server failed: %s", e)

    t = threading.Thread(target=_run, name="ws-bridge", daemon=True)
    t.start()
    return t


def handle_ws_info(body: dict | None = None) -> dict:
    """GET /api/v2/ws — discovery endpoint with the bridge connection URL."""
    return {"success": True, "url": f"ws://{API_GATEWAY_HOST}:{API_WS_PORT}",
            "protocol": "subscribe|unsubscribe|rpc"}
