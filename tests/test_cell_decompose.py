"""CellDecompose tests — card decomposition, role assignment."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCellDecompose:
    def test_decompose_card(self):
        from services.cell_decompose import decompose_card
        from services.card import Card
        card = Card(intent="modify config", domain="app/config")
        result = decompose_card(domain="app/config", card=card, cell_id="cell-1")
        assert result is not None
        assert isinstance(result, list)

    def test_auto_agent_map(self):
        from services.cell_decompose import auto_agent_map
        from services.card import Card, Phase, Step
        card = Card(intent="test", domain="t")
        card.phases.append(Phase(name="p", steps=[Step(action="read_file", target=".", agent="reader")]))
        mapping = auto_agent_map(card, cell_id="cell-1")
        assert len(mapping) >= 1
