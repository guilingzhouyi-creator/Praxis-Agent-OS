"""Prompts tests — prompt templates, system messages."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestPrompts:
    def test_get_prompt(self):
        from l1.kernel.prompts import get_prompt
        p = get_prompt("agent_loop.system")
        assert p is not None
        assert "agent" in p.lower()

    def test_get_prompt_not_found(self):
        from l1.kernel.prompts import get_prompt
        p = get_prompt("nonexistent")
        assert p is None or p == ""

    def test_list_prompts(self):
        from l1.kernel.prompts import list_prompts
        prompts = list_prompts()
        assert len(prompts) >= 3
        assert "agent_loop.system" in prompts
