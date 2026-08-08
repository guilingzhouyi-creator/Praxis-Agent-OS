"""CardPersistenceMixin — registry serialization for the PersistableMixin hook.

Extracted from card_registry.py (P2-1 split): the ``_serialize`` /
``_deserialize`` pair that PersistableMixin calls for the JSON snapshot.
Composed by CardRegistry alongside the stats / convention / dispatch mixins.
"""

from __future__ import annotations

import logging

from .card_unified import CardLifecycle, CardUnified

logger = logging.getLogger(__name__)


class CardPersistenceMixin:
    """Registry state serialization (cards + queue + cell map)."""

    def _serialize(self) -> dict:
        return {
            "cards": {cid: card.to_persist() for cid, card in self._cards.items()},
            "queue": list(self._queue),
            "cell_map": dict(self._cell_map),
        }

    def _deserialize(self, data: dict) -> bool:
        self._cards.clear()
        self._queue.clear()
        self._cell_map.clear()
        for cid, pd in data.get("cards", {}).items():
            card = CardUnified.from_persist(pd)
            if card.state not in (CardLifecycle.COMPLETED, CardLifecycle.FAILED, CardLifecycle.CANCELLED):
                pass
            self._cards[cid] = card
        self._queue[:] = data.get("queue", [])
        self._cell_map.update(data.get("cell_map", {}))
        return True
