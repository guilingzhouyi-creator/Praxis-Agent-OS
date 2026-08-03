"""Persistable mixin tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestPersistable:
    def test_importable(self):
        from l3._persistable import PersistableMixin
        assert callable(PersistableMixin)
