"""LLMWorkerServer — standalone LLM inference process.

Usage:
  python -m praxis.llm --socket /tmp/praxis-llm.sock --workers 4
  # or set env PRAXIS_ROLE=llm
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from l1.kernel.params.api import LLM_PROVIDER_MAX_TOKENS

logger = logging.getLogger(__name__)


class LLMWorkerServer:
    """LLM inference service running in a separate process."""

    def __init__(self, socket_path: str, workers: int = 4):
        self._socket_path = socket_path
        self._workers = workers
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        """Start the IPC server and begin accepting LLM worker connections."""
        from l1.kernel.platform import create_ipc_server
        self._server, self._address = await create_ipc_server(
            self._handle_client, self._socket_path,
        )
        logger.info("LLMWorkerServer listening on %s (%d workers)",
                     self._address, self._workers)

    async def stop(self) -> None:
        """Shut down the IPC server and remove the socket file."""
        from l1.kernel.platform import remove_ipc_socket
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        remove_ipc_socket(self._socket_path)

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        from l4.rpc.protocol import RpcMessage
        from l4.rpc.transport import RpcTransport
        try:
            raw = await RpcTransport.recv(reader)
            req = RpcMessage(**raw)
            if req.method == "llm.generate":
                result = await self._generate(req.params)
                await RpcTransport.send(writer, RpcMessage.response(req, result).to_dict())
            elif req.method == "llm.tool_use":
                result = await self._tool_use(req.params)
                await RpcTransport.send(writer, RpcMessage.response(req, result).to_dict())
            else:
                await RpcTransport.send(writer, RpcMessage.response(req, {}, f"unknown method: {req.method}").to_dict())
        except Exception as e:
            logger.warning("LLMWorkerServer handler: %s", e)
        finally:
            writer.close()

    async def _generate(self, params: dict) -> dict:
        from l4.llm.llm import get_engine
        engine = get_engine()
        prompt = params.get("prompt", "")
        system = params.get("system", "")
        result = engine.generate(prompt, system=system,
                                 max_tokens=params.get("max_tokens", LLM_PROVIDER_MAX_TOKENS),
                                 user_id=params.get("user_id", ""))
        return {"content": result.get("content", ""), "tokens": result.get("tokens", 0)}

    async def _tool_use(self, params: dict) -> dict:
        from l4.llm.llm import get_engine
        engine = get_engine()
        prompt = params.get("prompt", "")
        system = params.get("system", "")
        result = engine.tool_use(prompt, tools=params.get("tools", []),
                                 system=system,
                                 max_turns=params.get("max_turns", 5),
                                 user_id=params.get("user_id", ""))
        return {"content": result.get("content", ""),
                "tool_calls": result.get("tool_calls", []),
                "turns": result.get("turns", 0)}


def main() -> None:
    """CLI entry: run the LLM worker server on the configured socket."""
    socket_path = os.environ.get("PRAXIS_LLM_SOCKET", "")
    if not socket_path and len(sys.argv) > 2 and sys.argv[1] == "--socket":
        socket_path = sys.argv[2]
    if not socket_path:
        from l1.kernel.params.api import IPC_LLM_SOCKET
        socket_path = IPC_LLM_SOCKET

    logging.basicConfig(level=logging.INFO)
    server = LLMWorkerServer(socket_path)
    asyncio.run(server.start())
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        asyncio.run(server.stop())


if __name__ == "__main__":
    main()
