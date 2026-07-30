"""API handler: discussion tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestDiscussionHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_discussion import handle_discussion_start
        assert callable(handle_discussion_start)
