"""Cross-platform message transport: Unix socket or TCP fallback.

Transport:
  Unix (default):  Unix domain socket via asyncio.open_unix_connection
  Windows (TCP):   TCP localhost via asyncio.open_connection (connected to IPC_X_SOCKET = "127.0.0.1:port")

"""

from __future__ import annotations

import asyncio
import json
import logging
import struct

logger = logging.getLogger(__name__)

# ── Wire format constants ──
_RPC_HDR_FMT: str = "!I"
_RPC_HDR_SIZE: int = struct.calcsize(_RPC_HDR_FMT)


class RpcTransport:
    """Simple message transport: 4-byte length prefix + JSON encoding."""

    @staticmethod
    async def send(writer: asyncio.StreamWriter, data: dict) -> None:
        """Encode and write a message with a 4-byte length prefix."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        writer.write(struct.pack(_RPC_HDR_FMT, len(body)))
        writer.write(body)
        await writer.drain()

    @staticmethod
    async def recv(reader: asyncio.StreamReader) -> dict:
        """Read and decode one length-prefixed message from the reader."""
        raw = await reader.readexactly(_RPC_HDR_SIZE)
        length = struct.unpack(_RPC_HDR_FMT, raw)[0]
        body = await reader.readexactly(length)
        return json.loads(body.decode("utf-8"))
