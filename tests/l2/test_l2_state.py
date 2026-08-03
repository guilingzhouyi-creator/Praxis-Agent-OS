"""L2 shell state — session state tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestL2State:
    def test_importable(self):
        import l2.l2_shell.state as s
        assert s is not None

    def test_get_state(self):
        from l2.l2_shell.state import get_state
        state = get_state()
        assert state is not None
