"""L2 shell completer — additional completer tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCompleter:
    def test_importable(self):
        import l2.l2_shell.completer as c

        assert c is not None
