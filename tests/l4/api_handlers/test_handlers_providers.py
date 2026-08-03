"""API handler: providers tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestProvidersHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_providers import handle_providers_list
        assert callable(handle_providers_list)
