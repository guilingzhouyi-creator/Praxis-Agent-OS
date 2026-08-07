"""TransactionArea — card queue with human-in-the-loop tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestTransactionArea:
    def test_create(self):
        from l3.card.transaction_area import TransactionArea

        ta = TransactionArea(max_queue=10, persist_path="")
        assert ta is not None

    def test_enqueue(self):
        from l3.card.transaction_area import TransactionArea

        ta = TransactionArea(max_queue=10, persist_path="")
        r = ta.enqueue("test card", "app", size="small")
        assert isinstance(r, dict)
