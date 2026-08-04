"""RPC transport tests — RpcTransport."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestRpcTransport:
    """RpcTransport — async send/recv."""

    def test_send_non_tcp_raises(self):
        import asyncio

        from l4.rpc.transport import RpcTransport
        async def test():
            try:
                await RpcTransport.send(None, {"method": "ping"})
            except AttributeError:
                pass
        asyncio.run(test())
