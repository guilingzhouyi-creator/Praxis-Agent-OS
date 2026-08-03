"""Commands settings tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCommandsSettings:
    def test_importable(self):
        import l2.l2_shell.commands_settings as cs
        assert cs is not None

    def test_has_functions(self):
        from l2.l2_shell.commands_settings import _cmd_settings
        assert callable(_cmd_settings)
