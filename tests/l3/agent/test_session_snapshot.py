"""Session snapshot tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSessionSnapshot:
    def test_importable(self):
        from l3.agent.session_snapshot import SessionSnapshot
        assert callable(SessionSnapshot)
