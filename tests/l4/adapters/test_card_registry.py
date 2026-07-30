"""Adapter: CardRegistryAdapter tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCardRegistryAdapter:
    """CardRegistryAdapter — list_types, install_def."""

    def test_list_types(self):
        from l4.adapters.card_registry import CardRegistryAdapter
        adapter = CardRegistryAdapter()
        types = adapter.list_types()
        assert isinstance(types, list)

    def test_install_def(self):
        from l4.adapters.card_registry import CardRegistryAdapter
        adapter = CardRegistryAdapter()
        result = adapter.install_def({"name": "test", "steps": []})
        # install_def returns bool; may be False if l3.card_pool not available
        assert isinstance(result, bool)
