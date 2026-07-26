"""CardRegistryPort adapter — wraps services.card_unified behind the port interface.

Eliminates the ``from services.card_unified import list_card_types``
pattern in kernel layer.
"""

from __future__ import annotations

import logging
from typing import Any

from kernel.ports import CardRegistryPort

logger = logging.getLogger(__name__)


class CardRegistryAdapter(CardRegistryPort):
    """Delegates CardRegistryPort calls to ``services.card_unified``.

    This is the bridge that lets kernel code access card definitions
    through a Port interface instead of a direct import.
    """

    def list_types(self) -> list[dict]:
        try:
            from services.card_unified import list_card_types
            return list_card_types()
        except Exception as e:
            logger.warning("card_registry: list_types failed: %s", e)
            return []

    def install_def(self, cdef: dict, source: str = "") -> bool:
        try:
            from services.card_pool import get_pool
            pool = get_pool()
            pool._install_def(cdef, source=source or "peer:unknown")
            return True
        except Exception as e:
            logger.warning("card_registry: install_def failed: %s", e)
            return False
