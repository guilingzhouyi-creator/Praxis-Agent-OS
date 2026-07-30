"""CI service tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCI:
    def test_importable(self):
        from l4.ci import get_service
        assert callable(get_service)
