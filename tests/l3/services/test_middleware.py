"""Middleware — service middleware tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestMiddleware:
    def test_importable(self):
        from l3.services.middleware import ToolMiddleware, BeforeOutcome, AfterOutcome
        assert callable(ToolMiddleware)
