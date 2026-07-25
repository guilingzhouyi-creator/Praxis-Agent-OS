"""Network kernel module — cross-Cell communication and peer discovery.

Allows Cells on different machines to:
  - Discover each other via UDP broadcast or static config
  - Send cards/messages to remote Cells
  - Query remote Cell status
  - Forward L3B routing across machines

Protocol: JSON over TCP (lightweight, no framework dependency).
Discovery: UDP broadcast on a configurable port (default 42069).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .params import ENV_DISCOVERY_PORT, ENV_PRAXIS_PORT, DISCOVERY_PORT_DEFAULT, PRAXIS_PORT_DEFAULT, NET_PEER_TIMEOUT, BROADCAST_INTERVAL

logger = logging.getLogger(__name__)

_DISCOVERY_PORT = int(os.environ.get(ENV_DISCOVERY_PORT, str(DISCOVERY_PORT_DEFAULT)))
_PRAXIS_PORT = int(os.environ.get(ENV_PRAXIS_PORT, str(PRAXIS_PORT_DEFAULT)))
_BROADCAST_INTERVAL = BROADCAST_INTERVAL
_PEER_TIMEOUT = NET_PEER_TIMEOUT


@dataclass
class Peer:
    id: str
    host: str
    port: int
    last_seen: float = 0.0
    cell_count: int = 0
    version: str = ""

    @property
    def alive(self) -> bool:
        return time.time() - self.last_seen < _PEER_TIMEOUT


class NetKernel:
    """Network kernel — peer discovery + message transport.

    Usage:
      net = get_net()
      net.start(cell_id="cell-1")
      net.send_remote("cell-2", {"type": "card", "intent": "..."})
      peers = net.list_peers()
    """

    def __init__(self):
        self._node_id: str = ""
        self._port: int = _PRAXIS_PORT
        self._peers: dict[str, Peer] = {}
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._running = False

    def start(self, node_id: str = "", port: int = 0) -> dict:
        """Start network services: UDP discovery + TCP listener."""
        self._node_id = node_id or f"node-{socket.gethostname()}-{os.getpid()}"
        self._port = port or _PRAXIS_PORT
        self._running = True

        # UDP broadcast listener (discovery)
        threading.Thread(target=self._udp_listener, daemon=True).start()
        # UDP broadcast sender (announce)
        threading.Thread(target=self._udp_announcer, daemon=True).start()
        # TCP listener (message transport)
        threading.Thread(target=self._tcp_listener, daemon=True).start()

        logger.info("net started: %s on port %d (discovery %d)",
                     self._node_id, self._port, _DISCOVERY_PORT)
        return {"success": True, "node_id": self._node_id, "port": self._port}

    def stop(self) -> None:
        self._running = False

    def register_handler(self, msg_type: str, handler: Callable) -> None:
        """Register a handler for incoming message types."""
        with self._lock:
            self._handlers[msg_type] = handler

    def send_remote(self, target_node: str, payload: dict) -> dict:
        """Send a message to a remote peer. Returns success/failure."""
        with self._lock:
            peer = self._peers.get(target_node)
        if not peer or not peer.alive:
            return {"success": False, "error": f"peer '{target_node}' not found or dead"}
        try:
            data = json.dumps({
                "from": self._node_id,
                "type": payload.get("type", "message"),
                "payload": payload,
                "timestamp": time.time(),
            }).encode()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((peer.host, peer.port))
            s.sendall(data)
            s.close()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def broadcast_remote(self, payload: dict) -> list[dict]:
        """Send a message to all alive peers."""
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
                    for p in sorted(self._peers.values(), key=lambda x: x.last_seen, reverse=True)]

    def health(self) -> dict:
        """Return network health status."""
        with self._lock:
            now = time.time()
            total = len(self._peers)
            alive = sum(1 for p in self._peers.values() if p.alive and now - p.last_seen < 30)
            return {
                "status": "healthy" if alive >= 1 else "lonely",
                "peers_total": total, "peers_alive": alive,
                "peers_dead": total - alive,
                "node_id": self._node_id,
                "port": self._port,
                "uptime": round(now - self._started_at) if hasattr(self, '_started_at') else 0,
            }

    # ── UDP discovery ──

    def _udp_listener(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(5)
        try:
            sock.bind(("", _DISCOVERY_PORT))
        except OSError:
            logger.warning("discovery port %d in use", _DISCOVERY_PORT)
            return
        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
                announcement = json.loads(data.decode())
                peer_id = announcement.get("id", "")
                if peer_id and peer_id != self._node_id:
                    with self._lock:
                        self._peers[peer_id] = Peer(
                            id=peer_id, host=addr[0],
                            port=announcement.get("port", self._port),
                            last_seen=time.time(),
                            cell_count=announcement.get("cells", 0),
                            version=announcement.get("version", ""),
                        )
            except socket.timeout:
                continue
            except Exception:
                continue

    def _udp_announcer(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        announcement = json.dumps({
            "id": self._node_id,
            "port": self._port,
            "cells": 0,
            "version": "1.0",
        }).encode()
        while self._running:
            try:
                sock.sendto(announcement, ("255.255.255.255", _DISCOVERY_PORT))
            except Exception as e:
                logger.warning("kernel/net: %s", e)
            time.sleep(_BROADCAST_INTERVAL)

    # ── TCP message transport ──

    def _tcp_listener(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(5)
        try:
            sock.bind(("0.0.0.0", self._port))
            sock.listen(5)
        except OSError:
            logger.warning("port %d in use", self._port)
            return
        while self._running:
            try:
                conn, addr = sock.accept()
                threading.Thread(target=self._handle_conn,
                                 args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue

    def _handle_conn(self, conn: socket.socket, addr: tuple) -> None:
        try:
            data = conn.recv(65536)
            if not data:
                return
            msg = json.loads(data.decode())
            msg_type = msg.get("type", "message")
            with self._lock:
                handler = self._handlers.get(msg_type)
            if handler:
                try:
                    handler(msg)
                except Exception as e:
                    logger.error("handler error: %s", e)
        except Exception as e:
            logger.debug("conn error from %s: %s", addr[0], e)
        finally:
            conn.close()


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
