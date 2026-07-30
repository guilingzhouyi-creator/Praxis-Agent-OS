"""Identity service tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestIdentityService:
    def test_importable(self):
        from l3.services.identity import IdentityService
        assert callable(IdentityService)
