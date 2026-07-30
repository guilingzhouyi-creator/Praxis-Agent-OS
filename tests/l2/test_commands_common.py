"""Commands common tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCommandsCommon:
    def test_importable(self):
        import l2.l2_shell.commands.common as c
        assert c is not None

    def test_has_functions(self):
        from l2.l2_shell.commands.common import _parse_agent_ref
        assert callable(_parse_agent_ref)
