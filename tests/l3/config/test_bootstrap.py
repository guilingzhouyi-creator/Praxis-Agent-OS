"""Config bootstrap tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestBootstrap:
    def test_importable(self):
        from l3.config.bootstrap import default_config
        assert callable(default_config)
