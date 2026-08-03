"""Tests for cell_agent.py — extracted agent management module."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_add_agent_module():
    from l3.cell.components.cell_agent import add_agent, agent_status, liveness
    assert callable(add_agent)
    assert callable(agent_status)
    assert callable(liveness)


def test_ensure_terminal_module():
    from l3.cell.components.cell_agent import _boot_agent, _ensure_terminal, _inject_tools
    assert callable(_ensure_terminal)
    assert callable(_inject_tools)
    assert callable(_boot_agent)
