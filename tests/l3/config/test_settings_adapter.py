"""Settings adapter tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSettingsAdapter:
    def test_importable(self):
        from l3.config.settings_adapter import Settings

        assert callable(Settings)
