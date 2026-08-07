"""LLMWorkerServer tests — lifecycle and config."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestLLMWorkerServer:
    """LLMWorkerServer — init, start, stop."""

    def test_create_server(self):
        from l4.llm_worker.server import LLMWorkerServer

        srv = LLMWorkerServer(socket_path="/tmp/llm_test.sock", workers=2)
        assert srv._socket_path == "/tmp/llm_test.sock"
        assert srv._workers == 2

    def test_default_workers(self):
        from l4.llm_worker.server import LLMWorkerServer

        srv = LLMWorkerServer(socket_path="/tmp/llm_default.sock")
        assert srv._workers == 4

    def test_stop_without_start(self):
        from l4.llm_worker.server import LLMWorkerServer

        srv = LLMWorkerServer(socket_path="/tmp/llm_stop.sock")
        srv.stop()
