"""L3 base class tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestL3Base:
    def test_importable(self):
        from l3._base import BaseService
        assert callable(BaseService)
