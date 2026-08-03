"""Session export service tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSessionExport:
    def test_importable(self):
        from l3.services.session_export import SessionExport, SessionExportManager
        assert callable(SessionExport)
        assert callable(SessionExportManager)
