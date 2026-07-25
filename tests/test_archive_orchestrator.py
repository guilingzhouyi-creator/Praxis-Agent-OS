"""ArchiveOrchestrator tests — ring3 archiving, classify, restore."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestArchiveOrchestrator:
    def test_classify(self):
        from services.archive_orchestrator import _classify
        fonds, series = _classify({"agent_id": "agent-a", "entry_type": "tool_call"})
        assert "agent-a" in fonds
        assert series == "tool_call"

    def test_classify_unknown(self):
        from services.archive_orchestrator import _classify
        fonds, series = _classify({})
        assert fonds is not None
        assert series is not None

    def test_archive_ring3_empty(self):
        from services.archive_orchestrator import archive_ring3
        from services.memory import MemoryManager
        mem = MemoryManager()
        n = archive_ring3(mem)
        assert n >= 0

    def test_ring3_from_archive_empty(self):
        from services.archive_orchestrator import ring3_from_archive
        from services.memory import MemoryManager
        mem = MemoryManager()
        n = ring3_from_archive(mem)
        assert n >= 0
