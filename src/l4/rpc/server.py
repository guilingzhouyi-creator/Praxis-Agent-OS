"""RPC server — remote method invocation over the RpcTransport wire format.

Implements RpcServerPort: registered handlers are callable locally via
``call``/``notify`` and remotely over TCP/Unix sockets. Method names use
the full API path convention (``/api/v2/...``) so remote callers share
the same contract as HTTP and WebSocket clients; ``register_handler``
allows custom overrides.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable

from l1.kernel.params.api import API_GATEWAY_HOST, RPC_SERVER_PORT
from l1.kernel.ports import RpcServerPort
from l4.rpc.protocol import RpcMessage
from l4.rpc.transport import RpcTransport

logger = logging.getLogger(__name__)


class RpcServer(RpcServerPort):
    """RPC server — routes RpcMessage.method payloads to registered handlers."""

    def __init__(self, host: str = "", port: int = 0):
        self._host = host or API_GATEWAY_HOST
        self._port = port or RPC_SERVER_PORT
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._thread: threading.Thread | None = None

    def register_handler(self, method: str, handler: Callable) -> None:
        """Register a handler for an RPC method name."""
        with self._lock:
            self._handlers[method] = handler

    def unregister_handler(self, method: str) -> None:
        """Remove a registered RPC handler."""
        with self._lock:
            self._handlers.pop(method, None)

    def _resolve(self, method: str, params: dict) -> dict:
        """Resolve a method: explicit handler first, API route fallback."""
        with self._lock:
            handler = self._handlers.get(method)
        if handler:
            try:
                return handler(params or {})
            except Exception as e:
                return {"success": False, "error": f"rpc handler error: {e}"}
        from l4.ws.ws_bridge import _resolve_rpc

        return _resolve_rpc(method, params)

    def call(self, method: str, params: dict | None = None) -> dict:
        """Invoke a method synchronously. Returns the response payload."""
        return self._resolve(method, params or {})

    def notify(self, method: str, params: dict | None = None) -> None:
        """Send a one-way notification (no response expected)."""
        try:
            self._resolve(method, params or {})
        except Exception as e:
            logger.debug("rpc notify failed for %s: %s", method, e)

    # ── Server lifecycle ──

    def start(self) -> dict:
        """Start the async listener on a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return {"success": True, "already_running": True}

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._server = self._loop.run_until_complete(
                    asyncio.start_server(self._handle_conn, self._host, self._port)
                )
            except Exception as e:
                logger.warning("rpc server: listen failed on %s:%d: %s",
                               self._host, self._port, e)
                return
            logger.info("rpc server listening on %s:%d", self._host, self._port)
            try:
                self._loop.run_forever()
            finally:
                if self._server:
                    self._server.close()

        self._thread = threading.Thread(target=_run, name="rpc-server", daemon=True)
        self._thread.start()
        return {"success": True, "host": self._host, "port": self._port}

    def stop(self) -> None:
        """Stop the async server loop."""
        if self._loop and self._server:
            try:
                self._loop.call_soon_threadsafe(self._server.close)
            except Exception:
                pass

    async def _handle_conn(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter) -> None:
        """Serve one connection: recv RpcMessage -> route -> respond."""
        try:
            while True:
                try:
                    msg = await RpcTransport.recv(reader)
                except Exception:
                    break
                rpc_msg = RpcMessage(**msg)
                if rpc_msg.is_response:
                    continue
                result = self._resolve(rpc_msg.method, rpc_msg.params)
                resp = RpcMessage.response(rpc_msg, result)
                try:
                    await RpcTransport.send(writer, resp.to_dict())
                except Exception:
                    break
        finally:
            try:
                writer.close()
            except Exception:
                pass


_server: RpcServer | None = None
_server_lock = threading.Lock()


def get_server() -> RpcServer:
    """Get the RpcServer singleton (auto-start on first use)."""
    global _server
    if _server is None:
        with _server_lock:
            if _server is None:
                _server = RpcServer()
                _server.start()
                try:
                    from l1.kernel.ports import register_port

                    register_port("rpc", _server)
                except Exception:
                    logger.debug("rpc: port self-registration skipped")
    return _server


def reset_server() -> None:
    """Stop and drop the singleton (testing)."""
    global _server
    if _server:
        _server.stop()
    _server = None
