"""Card state types — re-exports CardUnified as the single card model.

CardRecord is now CardUnified (from card_unified.py).
CardState lifecycle enum kept here for backward compat.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .card_unified import CardUnified, CardLifecycle


class CardState(Enum):
    PENDING = auto()
    DISPATCHED = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()
    CANCELLED = auto()


# CardRecord is now CardUnified — the unified card model
CardRecord = CardUnified
