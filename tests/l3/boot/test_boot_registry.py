"""Boot registry — step registration and lifecycle tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestBootRegistry:
    def test_importable(self):
        from l3.boot.boot_registry import BootStep
        assert callable(BootStep)

    def test_register_boot_step_importable(self):
        from l3.boot.boot_registry import register_boot_step
        assert callable(register_boot_step)
