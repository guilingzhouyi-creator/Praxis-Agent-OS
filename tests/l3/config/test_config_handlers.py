"""Config handlers tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestConfigHandlers:
    def test_importable(self):
        from l3.config.config_handlers import cfg_kernel

        assert callable(cfg_kernel)
