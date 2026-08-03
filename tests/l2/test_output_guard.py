"""Output guard — output truncation/validation tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestOutputGuard:
    def test_importable(self):
        import l2.l2_shell.output_guard as og
        assert og is not None
