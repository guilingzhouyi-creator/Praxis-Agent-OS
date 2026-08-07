"""Error bus API tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestErrorBusApi:
    def test_handle_log_errors_importable(self):
        from l3.error_bus.api import handle_log_errors

        assert callable(handle_log_errors)

    def test_handle_log_errors_detail_importable(self):
        from l3.error_bus.api import handle_log_errors_detail

        assert callable(handle_log_errors_detail)
