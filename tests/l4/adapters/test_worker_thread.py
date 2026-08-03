"""Adapter: ThreadPoolWorker tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestThreadPoolWorker:
    """ThreadPoolWorker — submit, shutdown, stats."""

    def test_submit_returns_result(self):
        from l4.adapters.worker_thread import ThreadPoolWorker
        pool = ThreadPoolWorker(max_workers=2)
        result = pool.submit(lambda: 42)
        assert result.success
        pool.shutdown()

    def test_submit_multiple(self):
        from l4.adapters.worker_thread import ThreadPoolWorker
        pool = ThreadPoolWorker(max_workers=4)
        results = [pool.submit(lambda i=i: i * 2) for i in range(5)]
        assert all(r.success for r in results)
        pool.shutdown()

    def test_stats(self):
        from l4.adapters.worker_thread import ThreadPoolWorker
        pool = ThreadPoolWorker(max_workers=2)
        st = pool.stats()
        assert isinstance(st, dict)
        assert "active" in st
        pool.shutdown()

    def test_shutdown_idempotent(self):
        from l4.adapters.worker_thread import ThreadPoolWorker
        pool = ThreadPoolWorker(max_workers=2)
        pool.shutdown()
        pool.shutdown()
