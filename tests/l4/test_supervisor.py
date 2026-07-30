"""Supervisor service tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestSupervisor:
    def test_get_supervisor(self):
        from l4.supervisor import get_supervisor
        sup = get_supervisor()
        assert sup is not None
