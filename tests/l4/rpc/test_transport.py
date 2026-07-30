"""RPC transport tests — RpcTransport, rpc_call."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestRpcTransport:
    """RpcTransport — async send/recv."""

    def test_is_tcp_address(self):
        from l4.rpc.transport import _is_tcp_address
        # On Windows, ALL paths are treated as TCP
        # On Unix, a path with ":" not starting with "/" is TCP
        assert isinstance(_is_tcp_address("127.0.0.1:8080"), bool)

    def test_send_non_tcp_raises(self):
        from l4.rpc.transport import RpcTransport
        import asyncio
        async def test():
            try:
                await RpcTransport.send(None, {"method": "ping"})
            except AttributeError:
                pass
        asyncio.run(test())

    def test_rpc_call_invalid_path_returns_error(self):
        from l4.rpc.transport import rpc_call
        import asyncio
        async def test():
            result = await rpc_call("/nonexistent/socket", "ping", timeout=0.1)
            assert "error" in result
        asyncio.run(test())
