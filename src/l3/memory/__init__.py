"""Memory sub-module — four-tier hierarchical memory (Ring 1-4), paging, archive.

Package exports: the canonical MemoryManager API is re-exported here so both
internal callers (``l3.memory.memory``) and tests can import it as
``from l3.memory import get_memory``.
"""

from .memory import MemoryManager, get_memory, reset_memory  # noqa: F401
