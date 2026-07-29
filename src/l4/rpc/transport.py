"""Cross-platform message transport: Unix socket or TCP fallback.

Transport:
  Unix (default):  Unix domain socket via asyncio.open_unix_connection
  Windows (TCP):   TCP localhost via asyncio.open_connection (connected to IPC_X_SOCKET = "127.0.0.1:port")

socket_path format detection:
  "host:port"   → TCP
  "/path/file"  → Unix socket (default)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct

from l1.kernel.params.api import TRANSPORT_SOCKET_TIMEOUT
from l1.kernel.platform import IS_WINDOWS

logger = logging.getLogger(__name__)

# ── Wire format constants ──
_RPC_HDR_FMT: str = "!I"
_RPC_HDR_SIZE: int = struct.calcsize(_RPC_HDR_FMT)


def _is_tcp_address(path: str) -> bool:
    """Detect whether path is a host:port TCP address vs a Unix socket path."""
    if IS_WINDOWS:
        return True
    return ":" in path and not path.startswith("/")


class RpcTransport:
    """Simple message transport: 4-byte length prefix + JSON encoding."""

    @staticmethod
    async def send(writer: asyncio.StreamWriter, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        writer.write(struct.pack(_RPC_HDR_FMT, len(body)))
        writer.write(body)
        await writer.drain()

    @staticmethod
    async def recv(reader: asyncio.StreamReader) -> dict:
        raw = await reader.readexactly(_RPC_HDR_SIZE)
        length = struct.unpack(_RPC_HDR_FMT, raw)[0]
        body = await reader.readexactly(length)
        return json.loads(body.decode("utf-8"))


async def rpc_call(socket_path: str, method: str,
                   params: dict | None = None,
                   timeout: float = 300.0) -> dict:
    """Connect to IPC endpoint (Unix socket or TCP), send request, wait for response.

    ``socket_path`` format:
      Unix:   "/path/to/socket" (uses ``asyncio.open_unix_connection``)
      TCP:    "host:port"        (uses ``asyncio.open_connection``, e.g. "127.0.0.1:42100")
    """
    from .protocol import RpcMessage
    req = RpcMessage(method=method, params=params or {})
    try:
        if _is_tcp_address(socket_path):
            host, port_str = socket_path.rsplit(":", 1)
            port = int(port_str)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=TRANSPORT_SOCKET_TIMEOUT,
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path), timeout=TRANSPORT_SOCKET_TIMEOUT,
            )
        await RpcTransport.send(writer, req.to_dict())
        raw = await asyncio.wait_for(RpcTransport.recv(reader), timeout=timeout)
        writer.close()
        return raw
    except Exception as e:
        return {"id": req.id, "method": "rsp:" + method,
                "params": {}, "error": str(e)}
