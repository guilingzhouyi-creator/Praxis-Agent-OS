"""WebSocket bridge tests — real loopback connection, subscribe/rpc protocol."""

from __future__ import annotations

import json
import socket
import time

import pytest

from l1.kernel.params.api import API_WS_PORT


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def ws_server():
    from l4.ws.ws_bridge import start_server

    port = _free_port()
    t = start_server(port=port)
    # Wait for the listener to come up
    deadline = time.time() + 3.0
    ready = False
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                ready = True
                break
        except OSError:
            time.sleep(0.05)
    assert ready, "ws bridge did not start listening"
    yield port
    # daemon thread; no explicit stop needed for tests


@pytest.fixture
def client(ws_server):
    from websockets.sync.client import connect

    conn = connect(f"ws://127.0.0.1:{ws_server}")
    yield conn
    try:
        conn.close()
    except Exception:
        pass


def _send(conn, msg: dict) -> None:
    conn.send(json.dumps(msg))


def _recv(conn) -> dict:
    return json.loads(conn.recv())


class TestWsProtocol:
    def test_rpc_roundtrip(self, client):
        _send(client, {"type": "rpc", "method": "/api/v2/auth/login",
                       "params": {"identity": "ws-user"}})
        msg = _recv(client)
        assert msg["type"] == "rpc.result"
        assert msg["method"] == "/api/v2/auth/login"
        assert msg["data"]["success"] is True
        assert msg["data"]["token"]

    def test_rpc_unknown_method(self, client):
        _send(client, {"type": "rpc", "method": "/api/v2/does-not-exist"})
        msg = _recv(client)
        assert msg["type"] == "rpc.result"
        assert not msg["data"]["success"]

    def test_invalid_json(self, client):
        client.send("not json")
        msg = _recv(client)
        assert msg["type"] == "error"

    def test_unknown_message_type(self, client):
        _send(client, {"type": "teleport"})
        msg = _recv(client)
        assert msg["type"] == "error"

    def test_subscribe_unsubscribe_does_not_crash(self, client):
        _send(client, {"type": "subscribe", "events": ["card.pending"]})
        _send(client, {"type": "unsubscribe", "events": ["card.pending"]})
        # No response expected for subscribe; a subsequent rpc still works
        _send(client, {"type": "rpc", "method": "/api/v2/auth/login",
                       "params": {"identity": "x"}})
        msg = _recv(client)
        assert msg["type"] == "rpc.result"


class TestWsDiscovery:
    def test_ws_info_endpoint(self):
        from l4.ws.ws_bridge import handle_ws_info

        r = handle_ws_info(None)
        assert r["success"]
        assert r["url"].startswith("ws://")
        assert "subscribe" in r["protocol"]


class TestWsPortContract:
    def test_ws_port_registered_after_start(self, ws_server):
        from l1.kernel.ports import WebSocketPort, get_port

        port = get_port("ws")
        assert isinstance(port, WebSocketPort)

    def test_port_broadcast_reaches_subscribed_client(self, ws_server):
        import json as _json
        import time as _time

        from l4.ws.ws_bridge import WsBridgePort
        from websockets.sync.client import connect

        port = WsBridgePort()
        conn = connect(f"ws://127.0.0.1:{ws_server}")
        conn.send(_json.dumps({"type": "subscribe", "events": ["card.pending"]}))
        _time.sleep(0.3)  # let the server register the subscription
        port.broadcast("card.pending", {"card_id": "x"})
        msg = _json.loads(conn.recv())
        assert msg["type"] == "event" and msg["event"] == "card.pending"
        assert msg["data"]["card_id"] == "x"
        try:
            conn.close()
        except Exception:
            pass
