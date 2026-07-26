"""Transport layer — TcpAdapter(TransportPort) with pluggable worker/channel.

Architecture:
    NetKernel (business logic)
         │   TcpAdapter implements TransportPort
         ▼
    kernel.ports.TransportPort
         │
    TcpAdapter — uses WorkerPort for connection handling
               — uses ChannelPort for message buffering

Usage:
    from l1.kernel.net_transport import TcpAdapter, TransportConfig
    from l4.adapters.worker_thread import ThreadPoolWorker
    from l4.adapters.channel_ring import RingChannel

    adapter = TcpAdapter(worker_pool=ThreadPoolWorker(), msg_channel=RingChannel(CHANNEL_RING_CAPACITY))
    adapter.start("node-1", TransportConfig(port=42070))
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

from .params.api import (
    ENV_DISCOVERY_PORT,
    ENV_PRAXIS_PORT,
    DISCOVERY_PORT_DEFAULT,
    PRAXIS_PORT_DEFAULT,
    BROADCAST_INTERVAL,
    NET_TLS_ENABLED,
    NET_TLS_CERT_PATH,
    NET_TLS_KEY_PATH,
)
from .params.system import NET_PEER_TIMEOUT
from .ports import (
    TransportPort, WorkerPort, ChannelPort,
    Endpoint, Result as PortResult, Message,
)

logger = logging.getLogger(__name__)


# ── TransportConfig ──────────────────────────────────────────────────────────

@dataclass
class TransportConfig:
    """Transport-layer configuration, injected at start()."""
    host: str = "0.0.0.0"
    port: int = PRAXIS_PORT_DEFAULT
    discovery_port: int = DISCOVERY_PORT_DEFAULT
    broadcast_interval: float = BROADCAST_INTERVAL
    peer_timeout: float = NET_PEER_TIMEOUT
    socket_timeout: float = 10.0
    tls_enabled: bool = NET_TLS_ENABLED
    tls_cert_path: str = NET_TLS_CERT_PATH
    tls_key_path: str = NET_TLS_KEY_PATH


# ── TcpAdapter (TransportPort implementation) ────────────────────────────────

class TcpAdapter(TransportPort):
    """TCP-socket transport implementing ``TransportPort``.

    Incoming connections are handled via *worker_pool* (WorkerPort) instead
    of raw ``threading.Thread``.  Received messages are buffered through
    *msg_channel* (ChannelPort) for backpressure-aware consumption.
    """

    name = "tcp"

    def __init__(self,
                 worker_pool: WorkerPort | None = None,
                 msg_channel: ChannelPort | None = None):
        from l4.adapters.worker_thread import ThreadPoolWorker
        from l4.adapters.channel_ring import RingChannel

        self._worker: WorkerPort = worker_pool or ThreadPoolWorker()
        self._channel: ChannelPort = msg_channel or RingChannel()
        self._config: TransportConfig | None = None
        self._node_id: str = ""
        self._running = False
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []

    # ── Port lifecycle ───────────────────────────────────────────────────

    def start(self, node_id: str, config: Any) -> PortResult:
        self._node_id = node_id
        self._config = config if isinstance(config, TransportConfig) \
            else TransportConfig(port=int(config) if isinstance(config, (int, str)) else 42070)
        self._running = True
        cfg = self._config

        # UDP discovery threads
        threading.Thread(target=self._udp_listener, daemon=True,
                         name="tcp-udp-listen").start()
        threading.Thread(target=self._udp_announcer, daemon=True,
                         name="tcp-udp-announce").start()

        # TCP listener — connections submitted to worker pool
        threading.Thread(target=self._tcp_listener, daemon=True,
                         name="tcp-listen").start()

        logger.info("TcpAdapter started: %s port=%d discovery=%d",
                     node_id, cfg.port, cfg.discovery_port)
        return PortResult.ok(node_id=node_id, port=cfg.port,
                             transport=self.name)

    def stop(self) -> PortResult:
        self._running = False
        # Close sockets immediately to unblock listener threads
        for s in list(self._sockets):
            try:
                s.close()
            except Exception:
                pass
        self._sockets.clear()
        self._channel.close()
        self._worker.shutdown(wait=False)
        logger.info("TcpAdapter stopped: %s", self._node_id)
        return PortResult.ok(stopped=True)

    # ── Send ─────────────────────────────────────────────────────────────

    def send(self, target: Endpoint, data: bytes) -> PortResult:
        """Send raw bytes to a remote endpoint.

        Parses ``target.address`` as ``host:port``.
        I/O is synchronous (blocking) with a configurable socket timeout.
        """
        try:
            host, port_str = target.address.rsplit(":", 1)
            port = int(port_str)
        except (ValueError, AttributeError):
            return PortResult.fail(f"invalid endpoint: {target.address}")

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self._config.socket_timeout if self._config else 10)
            s.connect((host, port))
            s.sendall(data)
            s.close()
            return PortResult.ok(sent=True, target=target.address)
        except Exception as e:
            return PortResult.fail(str(e))

    def register_handler(self, msg_type: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[msg_type] = handler

    # ── Accessors ──

    def get_channel(self) -> ChannelPort:
        return self._channel

    def get_worker(self) -> WorkerPort:
        return self._worker

    # ── UDP discovery (listener) ──────────────────────────────────────────

    def _udp_listener(self) -> None:
        config = self._config
        if not config:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(5)
        try:
            sock.bind(("", config.discovery_port))
        except OSError:
            logger.warning("TcpAdapter: discovery port %d in use",
                           config.discovery_port)
            return
        self._sockets.append(sock)
        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
                self._on_announcement(data, addr)
            except socket.timeout:
                continue
            except Exception:
                continue

    def _on_announcement(self, data: bytes, addr: tuple) -> None:
        try:
            announcement = json.loads(data.decode())
            peer_id = announcement.get("id", "")
            if peer_id and peer_id != self._node_id:
                with self._lock:
                    handler = self._handlers.get("_peer_announce")
                if handler:
                    handler({"peer_id": peer_id, "host": addr[0],
                             "port": announcement.get("port", 0),
                             "cells": announcement.get("cells", 0),
                             "version": announcement.get("version", "")})
        except Exception:
            pass

    # ── UDP discovery (announcer) ─────────────────────────────────────────

    def _udp_announcer(self) -> None:
        config = self._config
        if not config:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sockets.append(sock)
        announcement = json.dumps({
            "id": self._node_id, "port": config.port,
            "cells": 0, "version": "1.0",
        }).encode()
        while self._running:
            try:
                sock.sendto(announcement, ("255.255.255.255", config.discovery_port))
            except Exception as e:
                logger.warning("TcpAdapter: announce error: %s", e)
            time.sleep(config.broadcast_interval)

    # ── TCP listener ─────────────────────────────────────────────────────

    def _tcp_listener(self) -> None:
        config = self._config
        if not config:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(5)
        self._sockets.append(sock)
        try:
            sock.bind((config.host, config.port))
            sock.listen(5)
        except OSError:
            logger.warning("TcpAdapter: port %d in use", config.port)
            self._sockets.remove(sock)
            sock.close()
            return
        while self._running:
            try:
                conn, addr = sock.accept()
                # Connection handling via worker pool — no raw Thread
                self._worker.submit(self._handle_conn, conn, addr)
            except socket.timeout:
                continue

    def _handle_conn(self, conn: socket.socket, addr: tuple) -> None:
        try:
            data = conn.recv(65536)
            if not data:
                return
            msg = json.loads(data.decode())
            msg_type = msg.get("type", "message")

            # Buffer via ChannelPort for backpressure-aware consumption
            self._channel.put(Message(
                type=msg_type,
                source=msg.get("from", addr[0]),
                payload=msg.get("payload", msg),
                timestamp=msg.get("timestamp", time.time()),
                headers={"remote_addr": addr[0]},
            ))

            # Also dispatch directly to handler (backward compat during migration)
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
