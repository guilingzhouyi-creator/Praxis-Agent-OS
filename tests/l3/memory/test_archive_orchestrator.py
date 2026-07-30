"""Archive orchestrator tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestArchiveOrchestrator:
    def test_importable(self):
        from l3.memory.archive_orchestrator import archive_ring3
        assert callable(archive_ring3)
