"""L3A — helpers (cardwrite, prompt builder, convergence) tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3AHelpers:
    def test_importable(self):
        from l3.cell.peers.l3a.helpers import set_card_counter
        assert callable(set_card_counter)
