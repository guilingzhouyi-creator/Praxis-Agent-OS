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
        """log channel always succeeds and records history."""
        from l4.notify import get_service

        svc = get_service()
        r = svc.send(channel="log", to="test-agent", subject="test", body="hello")
        assert isinstance(r, dict)
        assert r["success"] is True
        assert r["channel"] == "log"

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
