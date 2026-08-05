"""RPC server tests — local call/notify + real socket roundtrip."""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import time

import pytest

from l1.kernel.params.api import RPC_SERVER_PORT


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def rpc_port():
    from l4.rpc.server import RpcServer

    port = _free_port()
    srv = RpcServer(port=port)
    srv.start()
    deadline = time.time() + 3.0
    ready = False
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                ready = True
                break
        except OSError:
            time.sleep(0.05)
    assert ready
    yield port
    srv.stop()


class TestLocalCall:
    def test_api_route_call(self):
        from l4.rpc.server import RpcServer

        srv = RpcServer(port=0)
        r = srv.call("/api/v2/auth/login", {"identity": "rpc-local"})
        assert r["success"]
        assert r["token"]

    def test_unknown_method(self):
        from l4.rpc.server import RpcServer

        srv = RpcServer(port=0)
        r = srv.call("/api/v2/not-a-route")
        assert not r["success"]
        assert "unknown" in r["error"]

    def test_custom_handler(self):
        from l4.rpc.server import RpcServer

        srv = RpcServer(port=0)
        srv.register_handler("ping", lambda params: {"success": True, "pong": params})
        assert srv.call("ping", {"echo": 1}) == {"success": True, "pong": {"echo": 1}}

    def test_notify_swallows(self):
        from l4.rpc.server import RpcServer

        srv = RpcServer(port=0)
        srv.notify("/api/v2/not-a-route")  # must not raise


class TestSocketRoundtrip:
    def test_request_response_over_socket(self, rpc_port):
        async def client() -> dict:
            reader, writer = await asyncio.open_connection("127.0.0.1", rpc_port)
            msg = {"id": "t-1", "method": "/api/v2/auth/login",
                   "params": {"identity": "rpc-sock"}, "error": ""}
            body = json.dumps(msg).encode()
            writer.write(struct.pack("!I", len(body)))
            writer.write(body)
            await writer.drain()
            raw = await reader.readexactly(4)
            length = struct.unpack("!I", raw)[0]
            resp = json.loads(await reader.readexactly(length))
            writer.close()
            return resp

        resp = asyncio.run(client())
        assert resp["method"] == "rsp:/api/v2/auth/login"
        assert resp["params"]["success"] is True
        assert resp["params"]["token"]

    def test_unknown_method_over_socket(self, rpc_port):
        async def client() -> dict:
            reader, writer = await asyncio.open_connection("127.0.0.1", rpc_port)
            msg = {"id": "t-2", "method": "/api/v2/missing", "params": {}, "error": ""}
            body = json.dumps(msg).encode()
            writer.write(struct.pack("!I", len(body)))
            writer.write(body)
            await writer.drain()
            raw = await reader.readexactly(4)
            length = struct.unpack("!I", raw)[0]
            resp = json.loads(await reader.readexactly(length))
            writer.close()
            return resp

        resp = asyncio.run(client())
        assert resp["params"]["success"] is False
        assert "unknown" in resp["params"]["error"]
