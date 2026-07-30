"""Install phase tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestInstall:
    def test_importable(self):
        from l3.boot.install import install
        assert callable(install)
