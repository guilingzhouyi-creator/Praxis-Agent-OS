"""L2 shell completer — tab completion tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestShellCompleter:
    def test_importable(self):
        import l2.shell_completer as sc
        assert sc is not None

    def test_get_tool_names(self):
        from l2.shell_completer import get_tool_names
        names = get_tool_names()
        assert isinstance(names, list)
