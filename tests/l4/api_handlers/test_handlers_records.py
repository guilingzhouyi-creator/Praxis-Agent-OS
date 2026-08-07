"""API handler: records tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestRecordsHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_records import handle_records_query

        assert callable(handle_records_query)
