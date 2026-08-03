"""ArchiveOrchestrator tests — ring3 archiving, classify, restore."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestArchiveOrchestrator:
    def test_classify(self):
        from l3.memory.archive_orchestrator import _classify
        fonds, series = _classify({"agent_id": "agent-a", "entry_type": "tool_call"})
        assert "agent-a" in fonds
        assert series == "tool_call"

    def test_classify_unknown(self):
        from l3.memory.archive_orchestrator import _classify
        fonds, series = _classify({})
        assert fonds is not None
        assert series is not None

    def test_archive_ring3_empty(self):
        from l3.memory import MemoryManager
        from l3.memory.archive_orchestrator import archive_ring3
        mem = MemoryManager()
        n = archive_ring3(mem)
        assert n >= 0

    def test_ring3_from_archive_empty(self):
        from l3.memory import MemoryManager
        from l3.memory.archive_orchestrator import ring3_from_archive
        mem = MemoryManager()
        n = ring3_from_archive(mem)
        assert n >= 0
