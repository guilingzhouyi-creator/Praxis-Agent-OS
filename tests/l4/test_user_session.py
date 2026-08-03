"""User session tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestUserSession:
    def test_importable(self):
        from l4.user_session import UserSession
        assert callable(UserSession)
