"""Shell session — terminal session management tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestShellSession:
    def test_importable(self):
        import l2.shell_session as ss
        assert ss is not None

    def test_has_manager(self):
        from l2.shell_session import TerminalManager
        assert callable(TerminalManager)
