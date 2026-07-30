"""ContentTrust — content verification service tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestContentTrust:
    def test_get_trust(self):
        from l3.services.content_trust import get_trust
        trust = get_trust()
        assert trust is not None
