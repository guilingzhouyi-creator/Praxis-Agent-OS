"""SSE Bridge — EventBus over HTTP (Server-Sent Events)

将 kernel EventBus 的事件实时推送到 HTTP 客户端。
前端通过 EventSource /api/events 订阅。

用法:
  GET /api/events — SSE 流，持续推送事件
  GET /api/events?type=error_log — 按事件类型过滤
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# SSE 客户端注册表
_sse_clients: list[dict] = []  # [{"queue": Queue, "types": set, "id": str}]
_sse_lock = threading.RLock()
_client_counter = 0


def subscribe(event_types: set[str] | None = None) -> dict:
    """注册一个 SSE 客户端，返回客户端 ID 和消息队列。"""
    global _client_counter
    q: queue.Queue = queue.Queue(maxsize=256)
    with _sse_lock:
        _client_counter += 1
        client_id = f"sse-{_client_counter}"
        _sse_clients.append({
            "id": client_id,
            "queue": q,
            "types": event_types or set(),
        })
    # 订阅 EventBus
    try:
        from kernel import get_event_bus
        bus = get_event_bus()
        bus.on_event("sse_bridge", lambda sig: _broadcast(
            sig.type.name if hasattr(sig.type, 'name') else str(sig.type),
            sig.data if hasattr(sig, 'data') else {},
        ))
    except Exception as e:
        logger.warning("sse_bridge: event bus subscribe: %s", e)
    return {"client_id": client_id, "queue": q}


def _broadcast(event_type: str, data: Any) -> None:
    """向匹配的 SSE 客户端推送事件。"""
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
    """移除 SSE 客户端。"""
    with _sse_lock:
        _sse_clients[:] = [c for c in _sse_clients if c["id"] != client_id]


def push_event(event_type: str, data: Any) -> None:
    """外部入口：向 EventBus 推送事件（自动广播到 SSE）。"""
    try:
        from kernel import emit_event
        emit_event(event_type, data, source="sse_bridge")
    except Exception:
        pass
    _broadcast(event_type, data)


# 全局激活标记
_ACTIVE = False


def ensure_active() -> None:
    """确保 SSE 桥接已激活（自动订阅 EventBus）。"""
    global _ACTIVE
    if _ACTIVE:
        return
    try:
        from kernel import get_event_bus, SignalType
        bus = get_event_bus()
        # 注册通配符监听器：所有事件都广播
        bus.on_any(lambda sig: _broadcast(
            sig.type.name if hasattr(sig.type, 'name') else str(sig.type),
            sig.data if hasattr(sig, 'data') else {},
        ))
        _ACTIVE = True
        logger.info("sse_bridge: active, broadcasting all EventBus events")
    except Exception as e:
        logger.warning("sse_bridge: activation failed: %s", e)


# ══════════════════════════════════════════════════════════════════════
# API Handler
# ══════════════════════════════════════════════════════════════════════
#
# 注意：SSE handler 需要 HTTP Server 特殊处理（长连接）。
# 在 api_gateway.py 的 do_GET 中做特殊判断。


def handle_sse(body: dict | None = None) -> dict:
    """GET /api/events — SSE 流的特殊 handler。

    返回一个特殊的 dict 标记，HTTP server 读到这个标记
    切换到 SSE 模式（长连接 + text/event-stream）。
    """
    return {"_sse": True, "message": "SSE stream — use EventSource /api/events"}


# ── 路由 ──

SSE_ROUTES: list[tuple[str, str, Any, str]] = [
    ("GET", "/api/events", handle_sse, "SSE event stream (EventBus over HTTP)"),
]
