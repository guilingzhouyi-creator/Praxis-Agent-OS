"""Card state types — backward-compat re-exports.

CardRecord → CardUnified (from card_unified.py).
CardState → CardLifecycle alias for existing callers.
"""

from __future__ import annotations

from .card_unified import CardUnified, CardLifecycle

# Backward-compat: old code importing CardState still works
CardState = CardLifecycle
CardRecord = CardUnified
