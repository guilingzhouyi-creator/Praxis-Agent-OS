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
    adapter.start("node-1", TransportConfig(port=PRAXIS_PORT_DEFAULT))
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .params.api import (
    BROADCAST_INTERVAL,
    DISCOVERY_PORT_DEFAULT,
    NET_TLS_CERT_PATH,
    NET_TLS_ENABLED,
    NET_TLS_KEY_PATH,
    PRAXIS_PORT_DEFAULT,
    TCP_LISTEN_BACKLOG,
    TCP_RECV_BUF_SIZE,
    TRANSPORT_SOCKET_FAMILY,
    TRANSPORT_SOCKET_TIMEOUT,
    TRANSPORT_VERSION,
)
from .params.system import NET_PEER_TIMEOUT
from .ports import (
    ChannelPort,
    Endpoint,
    Message,
    TransportPort,
    WorkerPort,
)
from .ports import (
    Result as PortResult,
)

logger = logging.getLogger(__name__)


# ── Fallback implementations (no L4 dependency) ──────────────────────────────

class _FallbackWorker(WorkerPort):
    """Minimal thread-per-task worker — fallback when l4.adapters unavailable."""

    def __init__(self) -> None:
        self._threads: list[threading.Thread] = []

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> PortResult:
        t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
        t.start()
        self._threads.append(t)
        return PortResult.ok(submitted=True)

    def shutdown(self, wait: bool = True, timeout: float | None = None) -> PortResult:
        if wait:
            for t in self._threads:
                t.join(timeout=timeout)
        return PortResult.ok(shutdown=True)

    def stats(self) -> dict:
        alive = sum(1 for t in self._threads if t.is_alive())
        return {"total": len(self._threads), "alive": alive}


class _FallbackChannel(ChannelPort):
    """Simple deque-based channel — fallback when l4.adapters unavailable."""

    _UNBOUNDED_CAPACITY = 1_000_000

    def __init__(self) -> None:
        from collections import deque
        self._queue: deque = deque()
        self._closed = False

    def put(self, item: Any, timeout: float | None = None) -> bool:
        if self._closed:
            return False
        self._queue.append(item)
        return True

    def get(self, timeout: float | None = None) -> Any | None:
        # Drain remaining items even after close (matches RingChannel semantics)
        try:
            return self._queue.popleft()
        except IndexError:
            return None

    def size(self) -> int:
        return len(self._queue)

    def capacity(self) -> int:
        return self._UNBOUNDED_CAPACITY

    def close(self) -> None:
        self._closed = True


# ── TransportConfig ──────────────────────────────────────────────────────────

@dataclass
class TransportConfig:
    """Transport-layer configuration, injected at start()."""
    host: str = "0.0.0.0"
    port: int = PRAXIS_PORT_DEFAULT
    discovery_port: int = DISCOVERY_PORT_DEFAULT
    broadcast_interval: float = BROADCAST_INTERVAL
    peer_timeout: float = NET_PEER_TIMEOUT
    socket_timeout: float = TRANSPORT_SOCKET_TIMEOUT
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
        if worker_pool:
            self._worker: WorkerPort = worker_pool
        else:
            try:
                from l4.adapters.worker_thread import ThreadPoolWorker
                self._worker = ThreadPoolWorker()
            except ImportError:
                # Fallback: basic thread-per-task worker (no L4 dependency)
                self._worker = _FallbackWorker()

        if msg_channel:
            self._channel: ChannelPort = msg_channel
        else:
            try:
                from l4.adapters.channel_ring import RingChannel
                self._channel = RingChannel()
            except ImportError:
                # Fallback: simple deque-based channel (no L4 dependency)
                self._channel = _FallbackChannel()

        self._config: TransportConfig | None = None
        self._node_id: str = ""
        self._running = False
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []

    # ── Socket factory helpers (centralize address family for dual-stack) ──

    @staticmethod
    def _new_tcp_socket() -> socket.socket:
        """Create a TCP socket using the configured address family."""
        return socket.socket(TRANSPORT_SOCKET_FAMILY, socket.SOCK_STREAM)

    @staticmethod
    def _new_udp_socket() -> socket.socket:
        """Create a UDP socket using the configured address family."""
        return socket.socket(TRANSPORT_SOCKET_FAMILY, socket.SOCK_DGRAM)

    # ── Port lifecycle ───────────────────────────────────────────────────

    def start(self, node_id: str, config: Any) -> PortResult:
        self._node_id = node_id
        self._config = config if isinstance(config, TransportConfig) \
            else TransportConfig(port=int(config) if isinstance(config, (int, str)) else PRAXIS_PORT_DEFAULT)
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
        with self._lock:
            for s in list(self._sockets):
                try:
                    s.close()
                except Exception:
                    logger.debug("net: socket close error during stop")
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
            s = self._new_tcp_socket()
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
        sock = self._new_udp_socket()
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            logger.warning("TcpAdapter: can't set SO_REUSEADDR on UDP socket")
        sock.settimeout(5)
        try:
            sock.bind(("", config.discovery_port))
        except OSError:
            logger.warning("TcpAdapter: discovery port %d in use",
                           config.discovery_port)
            return
        with self._lock:
            self._sockets.append(sock)
        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
                self._on_announcement(data, addr)
            except TimeoutError:
                continue
            except Exception:
                logger.debug("discovery listener: unexpected error, continuing")
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
            logger.warning("discovery: failed to parse announcement from %s:%d", addr[0], addr[1])

    # ── UDP discovery (announcer) ─────────────────────────────────────────

    @staticmethod
    def _detect_broadcast_addr() -> str | None:
        """Attempt to detect the local subnet-directed broadcast address.

        Returns ``255.255.255.255`` on success (limited broadcast), or a
        subnet-directed address like ``192.168.1.255``, or ``None`` when the
        address family is not IPv4.
        """
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            # Very rough subnet guess: keep the first three octets, set the
            # last to 255.  This works for /24 networks (the most common case)
            # and fails gracefully (PermissionError) on non-/24 subnets.
            if local_ip.count(".") == 3:
                prefix = ".".join(local_ip.split(".")[:3])
                return f"{prefix}.255"
        except Exception:
            logger.debug("discovery: failed to resolve broadcast address")
        return None

    def _udp_announcer(self) -> None:
        config = self._config
        if not config:
            return
        sock = self._new_udp_socket()
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            logger.warning("TcpAdapter: SO_BROADCAST not allowed (permissions), "
                           "peer discovery disabled")
            sock.close()
            return
        with self._lock:
            self._sockets.append(sock)
        announcement = json.dumps({
            "id": self._node_id, "port": config.port,
            "cells": 0, "version": TRANSPORT_VERSION,
        }).encode()

        broadcast_addr = "255.255.255.255"
        while self._running:
            try:
                sock.sendto(announcement, (broadcast_addr, config.discovery_port))
            except PermissionError:
                logger.warning("TcpAdapter: UDP broadcast on %s requires "
                               "admin privileges — peer discovery disabled",
                               broadcast_addr)
                break
            except OSError as e:
                # EPERM, EACCES, or WSAEACCES on Windows; WSAEADDRNOTAVAIL
                if getattr(e, 'winerror', None) in (10013, 10049, 10051):
                    logger.debug("TcpAdapter: UDP broadcast blocked "
                                 "(winerror=%s)", getattr(e, 'winerror', '?'))
                    break
                # Invalid argument (e.g. non-/24 subnet with directed bcast)
                if getattr(e, 'errno', None) in (22,):
                    # Try subnet-directed broadcast if not already tried
                    if broadcast_addr == "255.255.255.255":
                        detected = self._detect_broadcast_addr()
                        if detected:
                            broadcast_addr = detected
                            continue
                    break
                logger.warning("TcpAdapter: announce error: %s", e)
            except Exception as e:
                logger.warning("TcpAdapter: announce error: %s", e)
            time.sleep(config.broadcast_interval)

    # ── TCP listener ─────────────────────────────────────────────────────

    def _tcp_listener(self) -> None:
        config = self._config
        if not config:
            return
        sock = self._new_tcp_socket()
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass  # Best-effort; may fail on Windows with exclusive port bindings
        sock.settimeout(5)
        with self._lock:
            self._sockets.append(sock)
        try:
            sock.bind((config.host, config.port))
            sock.listen(TCP_LISTEN_BACKLOG)
        except OSError:
            logger.warning("TcpAdapter: port %d in use", config.port)
            with self._lock:
                self._sockets.remove(sock)
            sock.close()
            return
        while self._running:
            try:
                conn, addr = sock.accept()
                # Connection handling via worker pool — no raw Thread
                self._worker.submit(self._handle_conn, conn, addr)
            except TimeoutError:
                continue

    def _handle_conn(self, conn: socket.socket, addr: tuple) -> None:
        try:
            data = conn.recv(TCP_RECV_BUF_SIZE)
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

            # Legacy direct handler dispatch (kept during migration; remove after
            # ALL consumers switch to ChannelPort consumption. Both paths fire
            # simultaneously, so only the ChannelPort path should remain.)
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
