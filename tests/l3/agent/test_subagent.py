"""Subagent — dispatch, gate, framework, merger, pool, spec, task tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSubagent:
    def test_dispatcher_importable(self):
        from l3.agent.subagent_dispatcher import SubAgentDispatcher

        assert callable(SubAgentDispatcher)

    def test_framework_get_dispatcher_importable(self):
        from l3.agent.subagent_framework import get_dispatcher

        assert callable(get_dispatcher)

    def test_gate_importable(self):
        from l3.agent.subagent_gate import classify_card

        assert callable(classify_card)

    def test_merger_importable(self):
        from l3.agent.subagent_merger import ResultMerger

        assert callable(ResultMerger)

    def test_pool_importable(self):
        from l3.agent.subagent_pool import SubAgentPool

        assert callable(SubAgentPool)

    def test_spec_importable(self):
        from l3.agent.subagent_spec import SubAgentSpec

        assert callable(SubAgentSpec)

    def test_task_importable(self):
        from l3.agent.subagent_task import SubAgentTask

        assert callable(SubAgentTask)

    def test_subagent_importable(self):
        from l3.agent.subagent import SubAgent

        assert callable(SubAgent)
