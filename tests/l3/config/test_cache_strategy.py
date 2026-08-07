"""Cache strategy tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCacheStrategy:
    def test_importable(self):
        from l3.config.cache_strategy import ConfigCacheStrategy

        assert callable(ConfigCacheStrategy)
