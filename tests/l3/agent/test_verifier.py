"""Verifier — agent self-check tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestVerifier:
    def test_importable(self):
        from l3.agent.verifier import Verifier
        assert callable(Verifier)
