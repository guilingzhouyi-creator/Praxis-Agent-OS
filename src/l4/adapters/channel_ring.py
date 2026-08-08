"""ChannelPort adapter — fixed-capacity ring buffer with backpressure.

Compatibility shim: the implementation lives in L1
(``l1.kernel.channel_ring``) and is re-exported here so existing
``l4.adapters.*`` import paths keep working.
"""

from __future__ import annotations

from l1.kernel.channel_ring import RingChannel  # noqa: F401

__all__ = ["RingChannel"]
