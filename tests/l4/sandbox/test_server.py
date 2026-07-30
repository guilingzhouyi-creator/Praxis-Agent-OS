"""Sandbox server tests — lifecycle."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSandboxServer:
    def test_create_server(self):
        from l4.sandbox.server import SandboxServer
        srv = SandboxServer(socket_path="/tmp/sandbox_test.sock")
        assert srv._socket_path == "/tmp/sandbox_test.sock"
