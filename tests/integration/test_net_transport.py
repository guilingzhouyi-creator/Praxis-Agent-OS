"""Tests for kernel.net_transport — TransportConfig + TcpAdapter(TransportPort).

Covers:
  - TransportConfig default and custom values
  - TcpAdapter construction with default/mock worker+channel
  - register_handler and send to unreachable host
  - TcpAdapter start/stop lifecycle (port 0 = ephemeral)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from l1.kernel.net_transport import TcpAdapter, TransportConfig
from l1.kernel.ports import Endpoint, TransportPort


class TestTransportConfig:
    def test_defaults(self):
        cfg = TransportConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 42070
        assert cfg.discovery_port == 42069
        assert cfg.socket_timeout == 10.0
        assert cfg.tls_enabled is False

    def test_custom_values(self):
        cfg = TransportConfig(host="127.0.0.1", port=9999,
                              discovery_port=8888, socket_timeout=5.0)
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9999
        assert cfg.discovery_port == 8888
        assert cfg.socket_timeout == 5.0


class TestTcpAdapterConstruction:
    def test_is_transport_port(self):
        from l4.adapters.channel_ring import RingChannel
        from l4.adapters.worker_thread import ThreadPoolWorker
        t = TcpAdapter(worker_pool=ThreadPoolWorker(min_workers=2, max_workers=4),
                       msg_channel=RingChannel(capacity=64))
        assert isinstance(t, TransportPort)
        assert t.name == "tcp"

    def test_default_creates_internals(self):
        t = TcpAdapter()
        assert t.get_worker() is not None
        assert t.get_channel() is not None

    def test_initial_state(self):
        t = TcpAdapter()
        assert not t._running


class TestTcpAdapterSend:
    def test_send_to_unreachable_host(self):
        t = TcpAdapter()
        t._config = TransportConfig(socket_timeout=0.5)
        ep = Endpoint("127.0.0.1:1", hint="tcp")
        r = t.send(ep, b"data")
        assert not r.success
        assert r.error != ""


class TestTcpAdapterHandlerRegistration:
    def test_register_and_call(self):
        t = TcpAdapter()
        captured = []
        def handler(msg):
            captured.append(msg)
        t.register_handler("test.type", handler)
        assert t._handlers.get("test.type") is handler
        t._handlers["test.type"]({"key": "value"})
        assert len(captured) == 1
        assert captured[0]["key"] == "value"

    def test_multiple_handlers(self):
        t = TcpAdapter()
        t.register_handler("a", lambda m: None)
        t.register_handler("b", lambda m: None)
        assert len(t._handlers) == 2


class TestTcpAdapterStartStop:
    def test_start_stop(self):
        t = TcpAdapter()
        cfg = TransportConfig(host="127.0.0.1", port=0, discovery_port=0)
        r = t.start("test-node", cfg)
        assert r.success
        assert r.data.get("node_id") == "test-node"
        t.stop()

    def test_start_sets_internal_config(self):
        t = TcpAdapter()
        cfg = TransportConfig(host="127.0.0.1", port=0, discovery_port=0)
        t.start("n1", cfg)
        assert t._config is cfg
        assert t._node_id == "n1"
        t.stop()

    def test_start_with_int_port(self):
        """start() accepts an int as config (convenience path)."""
        t = TcpAdapter()
        r = t.start("port-test", 0)
        assert r.success
        t.stop()

    def test_stop_closes_sockets(self):
        t = TcpAdapter()
        t.start("stop-test", TransportConfig(host="127.0.0.1", port=0, discovery_port=0))
        r = t.stop()
        assert r.success
        assert r.data.get("stopped") is True
