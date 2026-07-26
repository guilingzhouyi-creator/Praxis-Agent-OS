"""Network kernel module — cross-Cell communication and peer discovery.

Allows Cells on different machines to:
  - Discover each other via UDP broadcast or static config
  - Send cards/messages to remote Cells
  - Query remote Cell status
  - Forward L3B routing across machines

Architecture:
  NetKernel ── depends on ──► TransportPort / EventBusPort / I18nPort / CardRegistryPort
                                    │
                              TcpAdapter (default)

All dependencies are injected via ``kernel.ports`` — no direct ``from services.* import``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .params.api import PRAXIS_PORT_DEFAULT, ENV_PRAXIS_PORT
from .params.system import NET_PEER_TIMEOUT
from .net_transport import TransportConfig, TcpAdapter
from .ports import (
    TransportPort, EventBusPort, I18nPort, CardRegistryPort,
    Endpoint, Message, Event,
    get_port,
)

logger = logging.getLogger(__name__)

_PEER_TIMEOUT = NET_PEER_TIMEOUT


@dataclass
class Peer:
    id: str
    host: str
    port: int
    last_seen: float = 0.0
    cell_count: int = 0
    version: str = ""
    _loss_reported: bool = False

    @property
    def alive(self) -> bool:
        return time.time() - self.last_seen < _PEER_TIMEOUT


def _get_bus() -> EventBusPort | None:
    try:
        b = get_port("event_bus")
        return b if isinstance(b, EventBusPort) else None
    except KeyError:
        return None


def _get_i18n() -> I18nPort | None:
    try:
        i = get_port("i18n")
        return i if isinstance(i, I18nPort) else None
    except KeyError:
        return None


def _get_card_registry() -> CardRegistryPort | None:
    try:
        c = get_port("card_registry")
        return c if isinstance(c, CardRegistryPort) else None
    except KeyError:
        return None


def _emit_event(type_: str, severity: str, message: str,
                data: dict | None = None) -> None:
    bus = _get_bus()
    if bus:
        bus.emit(Event(
            type=type_, source="net",
            severity=severity, message=message,
            data=data or {},
        ))


class NetKernel:
    """Network kernel — peer discovery + message transport.

    Uses a ``TransportPort`` for the wire protocol.  Defaults to ``TcpAdapter``
    (plain TCP + UDP broadcast discovery).
    """

    def __init__(self, transport: TransportPort | None = None):
        self._transport: TransportPort = transport or TcpAdapter()
        self._node_id: str = ""
        self._port: int = 0
        self._peers: dict[str, Peer] = {}
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._running = False
        self._started_at: float = 0.0

    def start(self, node_id: str = "", port: int = 0,
              config: TransportConfig | None = None) -> dict:
        """Start network services: discovery + transport listener."""
        self._node_id = node_id or f"node-{socket.gethostname()}-{os.getpid()}"
        self._running = True
        self._started_at = time.time()

        if not config:
            resolved_port = port or int(os.environ.get(ENV_PRAXIS_PORT, str(PRAXIS_PORT_DEFAULT)))
            config = TransportConfig(port=resolved_port)
        self._port = config.port

        self._transport.register_handler("_peer_announce", self._on_peer_announce)
        self._transport.register_handler("message", self._on_message)
        self._transport.register_handler("card_registry_sync", self._on_card_registry_sync)

        result = self._transport.start(self._node_id, config)
        logger.info("net started: %s on transport=%s port=%d",
                     self._node_id, self._transport.name, self._port)
        return result

    def stop(self) -> None:
        self._running = False
        self._transport.stop()

    def register_handler(self, msg_type: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[msg_type] = handler

    # ── Card registry sync ───────────────────────────────────────────────

    def _on_card_registry_sync(self, msg: dict) -> None:
        """Handle card_registry_sync — install or respond with card types."""
        try:
            registry = _get_card_registry()
            if not registry:
                logger.warning("card_registry port not available")
                return

            cards = msg.get("cards") or (msg.get("payload") or {}).get("cards")
            if cards:
                for cdef in cards:
                    registry.install_def(cdef, source=f"peer:{msg.get('from', '?')}")
                return

            types = registry.list_types()
            payload = {"type": "card_registry_sync", "cards": types}
            self.send_remote(msg.get("from", ""), payload)
        except Exception as e:
            logger.warning("card_registry_sync handler: %s", e)

    # ── Send / broadcast ─────────────────────────────────────────────────

    def send_remote(self, target_node: str, payload: dict) -> dict:
        """Send a message to a remote peer. Returns success/failure."""
        peer: Peer | None = None
        with self._lock:
            p = self._peers.get(target_node)
            if p and p.alive:
                peer = Peer(id=p.id, host=p.host, port=p.port,
                            last_seen=p.last_seen)
        if not peer:
            return {"success": False, "error": f"peer '{target_node}' not found or dead"}

        i18n = _get_i18n()
        locale = i18n.get_locale() if i18n else "en"

        data = json.dumps({
            "from": self._node_id,
            "type": payload.get("type", "message"),
            "payload": payload,
            "timestamp": time.time(),
            "locale": locale,
        }).encode()

        ep = Endpoint(f"{peer.host}:{peer.port}", hint="tcp")
        r = self._transport.send(ep, data)
        return {"success": r.success, "error": r.error}

    def broadcast_remote(self, payload: dict) -> list[dict]:
        results = []
        with self._lock:
            peers = list(self._peers.values())
        for p in peers:
            if p.alive:
                r = self.send_remote(p.id, payload)
                results.append({"peer": p.id, **r})
        return results

    def list_peers(self) -> list[dict]:
        with self._lock:
            return [{"id": p.id, "host": p.host, "port": p.port,
                     "alive": p.alive, "cells": p.cell_count,
                     "last_seen": round(time.time() - p.last_seen, 1)}
                    for p in sorted(self._peers.values(),
                                    key=lambda x: x.last_seen, reverse=True)]

    def health(self) -> dict:
        """Return network health status. Uses consistent PEER_TIMEOUT."""
        with self._lock:
            now = time.time()
            total = len(self._peers)
            alive_peers = [p for p in self._peers.values() if p.alive]
            alive = len(alive_peers)
            for p in self._peers.values():
                if not p.alive and hasattr(p, '_loss_reported') and not p._loss_reported:
                    p._loss_reported = True
                    _emit_event(
                        type_="network.peer.loss",
                        severity="warn" if alive > 0 else "crit",
                        message=f"Peer {p.id} lost",
                        data={"peer_id": p.id},
                    )
            return {
                "status": "healthy" if alive >= 1 else "lonely",
                "peers_total": total, "peers_alive": alive,
                "peers_dead": total - alive,
                "node_id": self._node_id,
                "port": self._port,
                "uptime": round(now - self._started_at) if self._started_at else 0,
            }

    # ── Transport callbacks ──

    def _on_peer_announce(self, msg: dict) -> None:
        peer_id = msg.get("peer_id", "")
        if not peer_id or peer_id == self._node_id:
            return
        is_new = peer_id not in self._peers
        with self._lock:
            self._peers[peer_id] = Peer(
                id=peer_id, host=msg.get("host", ""),
                port=msg.get("port", self._port),
                last_seen=time.time(),
                cell_count=msg.get("cells", 0),
                version=msg.get("version", ""),
                _loss_reported=False,
            )
        if is_new:
            _emit_event(
                type_="network.peer.join",
                severity="info",
                message=f"Peer {peer_id} joined",
                data={"peer_id": peer_id},
            )

    def _on_message(self, raw: dict) -> None:
        msg_type = raw.get("type", "message")
        with self._lock:
            handler = self._handlers.get(msg_type)
        if handler:
            try:
                handler(raw)
            except Exception as e:
                logger.error("handler error: %s", e)


# ── Singleton ────────────────────────────────────────────────────────────────

_net: NetKernel | None = None


def get_net() -> NetKernel:
    global _net
    if _net is None:
        _net = NetKernel()
    return _net


def reset_net() -> None:
    global _net
    if _net:
        _net.stop()
    _net = None
