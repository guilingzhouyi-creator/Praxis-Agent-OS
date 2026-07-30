"""L3A tests — intent parsing, domain inference, card type detection (new package API)."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestL3A:
    def test_daemon_singleton(self):
        from l3.cell.peers.l3a import get_daemon
        d1 = get_daemon()
        d2 = get_daemon()
        assert d1 is d2

    def test_session_create_and_close(self):
        from l3.cell.peers.l3a.session import Session
        s = Session.create(title="test-parse")
        assert s is not None
        assert s.info()["status"] == "active"
        s.close()

