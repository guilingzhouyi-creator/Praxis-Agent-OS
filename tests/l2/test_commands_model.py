"""Commands model tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCommandsModel:
    def test_importable(self):
        import l2.l2_shell.commands.model as m
        assert m is not None

    def test_has_functions(self):
        from l2.l2_shell.commands.model import _cmd_config
        assert callable(_cmd_config)
