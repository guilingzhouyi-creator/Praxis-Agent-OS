"""Model service tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestModelService:
    def test_importable(self):
        from l3.services.model_service import get_service
        svc = get_service()
        assert svc is not None
