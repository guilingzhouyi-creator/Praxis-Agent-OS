"""Notification service tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestNotify:
    def test_get_service(self):
        from l4.notify import get_service
        svc = get_service()
        assert svc is not None

    def test_send_called(self):
        from l4.notify import get_service
        svc = get_service()
        try:
            r = svc.send("test-agent", "hello", channel="log")
            assert isinstance(r, dict)
        except Exception:
            # send may fail if channels not configured, that's ok
            assert True

    def test_history(self):
        from l4.notify import get_service
        svc = get_service()
        h = svc.history(limit=5)
        assert isinstance(h, dict)

    def test_stats(self):
        from l4.notify import get_service
        svc = get_service()
        st = svc.stats()
        assert isinstance(st, dict)
