"""L3A — model config (provider config, inheritance chain) tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3AModel:
    def test_importable(self):
        from l3.cell.peers.l3a.model import L3AModelConfig
        assert callable(L3AModelConfig)
