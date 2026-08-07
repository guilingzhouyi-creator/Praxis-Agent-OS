"""Pager bridge — integrates kernel Swapper with services ContextPager.

The Swapper moves memory entries between rings (hot→warm→cold).
The ContextPager manages context chunks in/out of working set.

Without integration:
  - Swapper may swap out entries the pager is actively using
  - Pager may load chunks that the swapper immediately evicts

With integration:
  - Pager registers active chunk IDs with swapper (pinned)
  - Swapper notifies pager before moving entries between rings
  - Pager can flush dirty chunks before they get swapped out
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class PagerBridge:
    """Bi-directional integration between kernel Swapper and services ContextPager.

    Usage:
      bridge = PagerBridge()
      bridge.attach_swapper(get_swapper())
      bridge.attach_pager(context_pager)
    """

    def __init__(self):
        self._swapper = None
        self._pager = None
        self._pinned_chunks: set[str] = set()  # chunk IDs the pager wants pinned
        self._lock = threading.Lock()

    def attach_swapper(self, swapper: Any) -> None:
        """Attach a swapper, wiring the bridge into it for swap notifications."""
        self._swapper = swapper
        swapper._pager_bridge = self
        logger.info("PagerBridge: swapper attached")

    def attach_pager(self, pager: Any) -> None:
        """Attach a context pager, wiring the bridge into it for pin calls."""
        self._pager = pager
        pager._pager_bridge = self
        logger.info("PagerBridge: pager attached")

    # ── Called by pager ──

    def pin_chunk(self, chunk_id: str) -> None:
        """Pager calls this when loading a chunk — prevents swapper from touching it."""
        with self._lock:
            self._pinned_chunks.add(chunk_id)

    def unpin_chunk(self, chunk_id: str) -> None:
        """Pager calls this when evicting a chunk — swapper can now swap it."""
        with self._lock:
            self._pinned_chunks.discard(chunk_id)

    # ── Called by swapper ──

    def on_swap_out(self, entry_ids: list[str], from_ring: int, to_ring: int) -> list[str]:
        """Swapper calls this before moving entries. Returns IDs that should NOT be moved (pinned)."""
        with self._lock:
            pinned = {e for e in entry_ids if e in self._pinned_chunks}
            if pinned:
                logger.debug("PagerBridge: %d entries pinned, skipping swap", len(pinned))
            return list(pinned)

    def on_before_evict(self, entry_ids: list[str]) -> None:
        """Swapper calls this before evicting entries. Pager can flush dirty chunks."""
        if not self._pager:
            return
        for eid in entry_ids:
            try:
                self._pager.flush(eid)
            except Exception as e:
                logger.warning("services/pager_bridge: %s", e)

    def is_pinned(self, chunk_id: str) -> bool:
        """Check whether a chunk is currently pinned against swapping."""
        with self._lock:
            return chunk_id in self._pinned_chunks

    def stats(self) -> dict:
        """Return bridge stats: pinned chunk count and attachment status."""
        with self._lock:
            return {
                "pinned_chunks": len(self._pinned_chunks),
                "swapper_attached": self._swapper is not None,
                "pager_attached": self._pager is not None,
            }


_bridge: PagerBridge | None = None


def get_pager_bridge() -> PagerBridge:
    """Get the PagerBridge singleton, creating it on first call."""
    global _bridge
    if _bridge is None:
        _bridge = PagerBridge()
    return _bridge


def reset_pager_bridge() -> None:
    """Reset the PagerBridge singleton (for testing)."""
    global _bridge
    _bridge = None
