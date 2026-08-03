"""Network service tests — NetKernel (with TransportPort mock) + NetworkService.

MockTransport implements ``kernel.ports.TransportPort`` for isolated unit tests
without real sockets.
"""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from l1.kernel.ports import Endpoint, TransportPort
from l1.kernel.ports import Result as PortResult

# ── Mock transport (TransportPort implementation) ──

class MockTransport(TransportPort):
    """Simulates TransportPort without real sockets."""
    name = "mock"

    def __init__(self):
        self._handlers: dict[str, callable] = {}
        self._sent: list[tuple[str, int, bytes]] = []
        self._lock = threading.Lock()

    def start(self, node_id: str, config) -> PortResult:
        return PortResult.ok(node_id=node_id)

    def stop(self) -> PortResult:
        return PortResult.ok(stopped=True)

    def send(self, target: Endpoint, data: bytes) -> PortResult:
        with self._lock:
            # Parse host:port from Endpoint.address
            host, port_str = target.address.rsplit(":", 1)
            self._sent.append((host, int(port_str), data))
        return PortResult.ok(sent=True)

    def register_handler(self, msg_type: str, handler: callable):
        with self._lock:
            self._handlers[msg_type] = handler


class TestNetKernel:
    def test_create_default_transport(self):
        from l1.kernel.net import NetKernel
        nk = NetKernel()
        assert nk._transport.name == "tcp"

    def test_create_with_mock(self):
        from l1.kernel.net import NetKernel
        mock = MockTransport()
        nk = NetKernel(transport=mock)
        assert nk._transport is mock

    def test_start_stop_with_mock(self):
        from l1.kernel.net import NetKernel
        nk = NetKernel(transport=MockTransport())
        r = nk.start(node_id="test-node", port=9999)
        assert r.get("success") if isinstance(r, dict) else r.success
        assert nk._node_id == "test-node"
        nk.stop()

    def test_register_handler(self):
        from l1.kernel.net import NetKernel
        nk = NetKernel(transport=MockTransport())
        calls = []
        def handler(msg): calls.append(msg)
        nk.register_handler("foo", handler)
        nk._handlers["foo"]({"x": 1})
        assert len(calls) == 1
        assert calls[0]["x"] == 1

    def test_send_remote_no_peer(self):
        from l1.kernel.net import NetKernel
        nk = NetKernel(transport=MockTransport())
        r = nk.send_remote("unknown-peer", {"type": "test"})
        assert not r.get("success")
        assert "not found" in r.get("error", "")

    def test_send_remote_with_peer(self):
        import time

        from l1.kernel.net import NetKernel, Peer
        mock = MockTransport()
        nk = NetKernel(transport=mock)
        nk._node_id = "sender"
        nk._peers["peer-1"] = Peer(
            id="peer-1", host="10.0.0.2", port=8888,
            last_seen=time.time(),
        )
        r = nk.send_remote("peer-1", {"type": "card", "intent": "fix bug"})
        assert r.get("success")
        assert len(mock._sent) == 1
        host, port, data = mock._sent[0]
        assert host == "10.0.0.2"
        assert port == 8888
        import json
        msg = json.loads(data.decode())
        assert msg["from"] == "sender"
        assert msg["type"] == "card"
        assert msg["payload"]["intent"] == "fix bug"

    def test_broadcast_remote_pings_alive_peers(self):
        import time

        from l1.kernel.net import NetKernel, Peer
        mock = MockTransport()
        nk = NetKernel(transport=mock)
        now = time.time()
        nk._peers["alive-1"] = Peer(id="alive-1", host="10.0.0.2", port=1111, last_seen=now)
        nk._peers["alive-2"] = Peer(id="alive-2", host="10.0.0.3", port=2222, last_seen=now)
        nk._peers["dead-1"] = Peer(id="dead-1", host="10.0.0.4", port=3333, last_seen=now - 9999)
        results = nk.broadcast_remote({"type": "ping"})
        assert len(results) == 2
        assert all(r.get("success") for r in results)

    def test_health_empty(self):
        from l1.kernel.net import NetKernel
        nk = NetKernel(transport=MockTransport())
        h = nk.health()
        assert h["status"] == "lonely"
        assert h["peers_total"] == 0

    def test_health_with_alive_peer(self):
        import time

        from l1.kernel.net import NetKernel, Peer
        nk = NetKernel(transport=MockTransport())
        nk._peers["p1"] = Peer(id="p1", host="10.0.0.2", port=8888, last_seen=time.time())
        h = nk.health()
        assert h["peers_total"] == 1
        assert h["peers_alive"] >= 1

    def test_list_peers(self):
        import time

        from l1.kernel.net import NetKernel, Peer
        nk = NetKernel(transport=MockTransport())
        now = time.time()
        nk._peers["a"] = Peer(id="a", host="10.0.0.2", port=1111, last_seen=now)
        nk._peers["b"] = Peer(id="b", host="10.0.0.3", port=2222, last_seen=now - 100)
        peers = nk.list_peers()
        assert len(peers) == 2

    def test_peer_on_announce_new_peer(self):
        from l1.kernel.net import NetKernel
        nk = NetKernel(transport=MockTransport())
        nk._node_id = "self-node"
        nk._on_peer_announce({
            "peer_id": "new-peer",
            "host": "10.0.0.5",
            "port": 7777,
            "cells": 2,
            "version": "1.0",
        })
        assert "new-peer" in nk._peers
        p = nk._peers["new-peer"]
        assert p.host == "10.0.0.5"
        assert p.port == 7777
        assert p.cell_count == 2
        assert p.version == "1.0"

    def test_peer_on_announce_ignores_self(self):
        from l1.kernel.net import NetKernel
        nk = NetKernel(transport=MockTransport())
        nk._node_id = "self-node"
        nk._peers.clear()
        nk._on_peer_announce({"peer_id": "self-node", "host": "127.0.0.1", "port": 9999})
        assert "self-node" not in nk._peers


class TestNetworkService:
    def test_service_create(self):
        from l4.network import NetworkService
        svc = NetworkService()
        assert svc is not None

    def test_start_stop(self):
        from l4.network import NetworkService
        svc = NetworkService()
        r = svc.start()
        assert r.get("success")
        r2 = svc.stop()
        assert r2.get("success")

    def test_register_service(self):
        from l4.network import NetworkService
        svc = NetworkService()
        r = svc.register_service("test-api", "localhost", 8080)
        assert r is None or r.get("success", True)
