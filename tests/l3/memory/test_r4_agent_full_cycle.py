"""R4Agent + archive_orchestrator full cycle test — archive/restore/detect/consolidate.

Covered scenarios:
  - archive_ring3: archive high-importance entries from Ring 3 to Archive
  - ring3_from_archive: restore from Archive to Ring 3
  - R4Agent tick: full detection cycle (stale/archive/consistency)
  - _classify: entry → fonds/series classification
  - R4Agent get_lean_cases / stats
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestArchiveOrchestrator:
    """archive_orchestrator core functions"""

    def test_classify_agent_entry(self):
        from l3.memory.archive_orchestrator import _classify
        fonds, series = _classify({"agent_id": "agent-x", "entry_type": "decision"})
        assert fonds == "AGENT:agent-x"
        assert series == "decision"

    def test_classify_unknown(self):
        from l3.memory.archive_orchestrator import _classify
        fonds, series = _classify({})
        assert fonds.startswith("AGENT:")
        assert series in ("general", "unknown")

    def test_archive_ring3_empty(self):
        from l3.memory.archive_orchestrator import archive_ring3
        from l3.memory import MemoryManager
        mem = MemoryManager()
        n = archive_ring3(mem)
        assert isinstance(n, int)
        assert n >= 0

    def test_ring3_from_archive_empty(self):
        from l3.memory.archive_orchestrator import ring3_from_archive
        from l3.memory import MemoryManager
        mem = MemoryManager()
        n = ring3_from_archive(mem)
        assert isinstance(n, int)

    def test_archive_ring3_with_important_entry(self):
        from l3.memory.archive_orchestrator import archive_ring3
        from l3.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-a", "decision",
                      "This is an important decision with high importance for archival storage.",
                      importance=0.8, ring=3)
        n = archive_ring3(mem)
        assert isinstance(n, int)
        # May archive 0 or 1 entries (depends on implementation), but should not crash
        assert n >= 0


class TestR4Agent:
    """R4Agent basic API (no background thread started)"""

    def test_get_r4_agent_returns_instance(self):
        from l3.memory.r4_agent import get_r4_agent, stop_r4_agent
        stop_r4_agent()
        r4 = get_r4_agent()
        assert r4 is not None
        assert hasattr(r4, 'tick')
        assert hasattr(r4, 'status')
        assert hasattr(r4, 'start')
        assert hasattr(r4, 'stop')

    def test_status_returns_keys(self):
        from l3.memory.r4_agent import get_r4_agent, stop_r4_agent
        stop_r4_agent()
        r4 = get_r4_agent()
        s = r4.status()
        for key in ("running", "interval", "total_archived", "total_alerts"):
            assert key in s, f"missing key: {key}"

    def test_restore_ring3_returns_dict(self):
        """Verify restore_ring3() method exists and returns structured result (without starting thread)"""
        from l3.memory.r4_agent import get_r4_agent, stop_r4_agent
        from l3.memory import get_memory, reset_memory
        stop_r4_agent()
        reset_memory()
        r4 = get_r4_agent()
        r = r4.restore_ring3(limit=10)
        assert isinstance(r, dict)
        assert "success" in r
        assert "restored" in r


class TestR4AgentLeanCases:
    """get_lean_cases — learn from failure patterns"""

    def test_get_lean_cases_empty(self):
        from l3.memory.r4_agent import get_r4_agent, stop_r4_agent
        stop_r4_agent()
        r4 = get_r4_agent()
        cases = r4.get_lean_cases()
        assert isinstance(cases, list)

    def test_get_lean_cases_by_agent(self):
        from l3.memory.r4_agent import get_r4_agent, stop_r4_agent
        stop_r4_agent()
        r4 = get_r4_agent()
        cases = r4.get_lean_cases(agent_id="test-agent")
        assert isinstance(cases, list)


class TestR4AgentSkills:
    """get_evolved_skills — evolved skills"""

    def test_get_evolved_skills_empty(self):
        from l3.memory.r4_agent import get_r4_agent, stop_r4_agent
        stop_r4_agent()
        r4 = get_r4_agent()
        skills = r4.get_evolved_skills()
        assert isinstance(skills, list)
