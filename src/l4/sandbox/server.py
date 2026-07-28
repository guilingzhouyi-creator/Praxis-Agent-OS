"""SandboxServer — standalone sandbox execution process.

Usage:
  python -m praxis.sandbox --socket /tmp/praxis-sandbox.sock
  # or set env PRAXIS_ROLE=sandbox
"""

from __future__ import annotations

import asyncio
import logging
import os

from l4.sandbox.manager import SandboxManager, SandboxProfile, SandboxResult

logger = logging.getLogger(__name__)


class SandboxServer:
    """Sandbox execution service for an independent process."""

    def __init__(self, socket_path: str):
        self._socket_path = socket_path
        self._manager = SandboxManager()
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        from l1.kernel.platform import create_ipc_server
        self._server, self._address = await create_ipc_server(
            self._handle_client, self._socket_path,
        )
        logger.info("SandboxServer listening on %s", self._address)

    async def stop(self) -> None:
        from l1.kernel.platform import remove_ipc_socket
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        remove_ipc_socket(self._socket_path)

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        from l4.rpc.transport import RpcTransport
        from l4.rpc.protocol import RpcMessage
        try:
            raw = await RpcTransport.recv(reader)
            req = RpcMessage(**raw)
            if req.method == "sandbox.run":
                result = await self._manager.run(
                    command=req.params.get("command", ""),
                    profile=SandboxProfile(req.params.get("profile", SANDBOX_PROFILE_READ_ONLY)),
                    timeout=req.params.get("timeout", 30),
                    agent_id=req.params.get("agent_id", ""),
                    tool_name=req.params.get("tool_name", ""),
                )
                await RpcTransport.send(
                    writer,
                    RpcMessage.response(req, result.to_dict()).to_dict(),
                )
            else:
                await RpcTransport.send(
                    writer,
                    RpcMessage.response(req, {}, f"unknown method: {req.method}").to_dict(),
                )
        except Exception as e:
            logger.warning("SandboxServer handler: %s", e)
        finally:
            writer.close()


def main() -> None:
    import sys
    socket_path = os.environ.get("PRAXIS_SANDBOX_SOCKET", "")
    if not socket_path and len(sys.argv) > 2 and sys.argv[1] == "--socket":
        socket_path = sys.argv[2]
    if not socket_path:
        from l1.kernel.params.api import IPC_SANDBOX_SOCKET
        socket_path = IPC_SANDBOX_SOCKET

    logging.basicConfig(level=logging.INFO)
    server = SandboxServer(socket_path)
    asyncio.run(server.start())
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        asyncio.run(server.stop())


if __name__ == "__main__":
    main()
