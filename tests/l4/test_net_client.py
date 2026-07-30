"""Net client tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestNetClient:
    def test_importable(self):
        from l4.net_client import NetClient
        assert callable(NetClient)
