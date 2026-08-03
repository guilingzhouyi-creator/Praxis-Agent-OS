"""Review — peer review tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestReview:
    def test_request_review_importable(self):
        from l3.agent.review import request_review
        assert callable(request_review)
