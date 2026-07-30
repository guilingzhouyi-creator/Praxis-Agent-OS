"""L3A — prompt inbox (durable admission/promotion) tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3AInbox:
    def test_importable(self):
        from l3.cell.peers.l3a.inbox import PromptInbox
        assert callable(PromptInbox)
