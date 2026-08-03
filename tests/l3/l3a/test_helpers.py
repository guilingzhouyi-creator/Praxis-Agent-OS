"""L3A — helpers (cardwrite, prompt builder, convergence) tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3AHelpers:
    def test_importable(self):
        from l3.cell.peers.l3a.helpers import (
            _route_to_assembly,
            build_l3a_prompt,
            cardwrite_handler,
            get_convergence_queue,
        )
        assert callable(cardwrite_handler)
        assert callable(build_l3a_prompt)
        assert callable(get_convergence_queue)
        assert callable(_route_to_assembly)

    def test_build_l3a_prompt(self):
        from l3.cell.peers.l3a.helpers import build_l3a_prompt
        prompt = build_l3a_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_get_convergence_queue_empty(self):
        from l3.cell.peers.l3a.helpers import get_convergence_queue
        r = get_convergence_queue("nonexistent-cell")
        assert isinstance(r, list)
