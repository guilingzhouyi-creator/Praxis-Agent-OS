"""Commands extra tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCommandsExtra:
    def test_importable(self):
        import l2.l2_shell.commands.extra as e

        assert e is not None

    def test_has_cmd_think(self):
        from l2.l2_shell.commands.extra import _cmd_think

        assert callable(_cmd_think)
