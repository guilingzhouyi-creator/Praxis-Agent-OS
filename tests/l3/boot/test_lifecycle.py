"""Boot lifecycle — factory reset, singleton reset tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestLifecycle:
    def test_shutdown_importable(self):
        from l3.boot.lifecycle import shutdown
        assert callable(shutdown)

    def test_reset_all_singletons_importable(self):
        from l3.boot.lifecycle import reset_all_singletons
        assert callable(reset_all_singletons)
