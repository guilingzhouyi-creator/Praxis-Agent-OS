"""Ops console tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestOpsConsole:
    def test_get_ops(self):
        from l4.ops_console import get_ops
        ops = get_ops()
        assert ops is not None

    def test_summary(self):
        from l4.ops_console import get_ops
        ops = get_ops()
        s = ops.summary()
        assert isinstance(s, dict)

    def test_health(self):
        from l4.ops_console import get_ops
        ops = get_ops()
        h = ops.health()
        assert isinstance(h, dict)

    def test_recent_alerts(self):
        from l4.ops_console import get_ops
        ops = get_ops()
        alerts = ops.recent_alerts(limit=5)
        assert isinstance(alerts, list)
