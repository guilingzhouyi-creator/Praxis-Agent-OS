"""Subscriptions + Notifications tests — event subscription, multi-channel delivery."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestNotifications:
    def test_notify_create(self):
        from l4.notify import NotifyService
        svc = NotifyService()
        assert svc is not None

    def test_notify_log(self):
        from l4.notify import NotifyService
        svc = NotifyService()
        r = svc.send("log", "system", "test notification", "body")
        assert r.get("success")
