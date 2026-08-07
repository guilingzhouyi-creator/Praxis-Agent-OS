"""API handler: constitution tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestConstitutionHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_constitution import handle_constitution_get

        assert callable(handle_constitution_get)
