"""Unix Socket msgpack transport for inter-process RPC."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct

logger = logging.getLogger(__name__)


class RpcTransport:
    """Simple message transport: 4-byte length prefix + JSON encoding."""

    @staticmethod
    async def send(writer: asyncio.StreamWriter, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        writer.write(struct.pack("!I", len(body)))
        writer.write(body)
        await writer.drain()

    @staticmethod
    async def recv(reader: asyncio.StreamReader) -> dict:
        raw = await reader.readexactly(4)
        length = struct.unpack("!I", raw)[0]
        body = await reader.readexactly(length)
        return json.loads(body.decode("utf-8"))


async def rpc_call(socket_path: str, method: str,
                   params: dict | None = None,
                   timeout: float = 300.0) -> dict:
    """Connect to Unix socket, send request, wait for response."""
    from .protocol import RpcMessage
    req = RpcMessage(method=method, params=params or {})
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path), timeout=10,
        )
        await RpcTransport.send(writer, req.to_dict())
        raw = await asyncio.wait_for(RpcTransport.recv(reader), timeout=timeout)
        writer.close()
        return raw
    except Exception as e:
        return {"id": req.id, "method": "rsp:" + method,
                "params": {}, "error": str(e)}
