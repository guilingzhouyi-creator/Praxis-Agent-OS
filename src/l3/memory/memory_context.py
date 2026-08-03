"""Memory context builder — extracted from memory.py for modularity.

Contains MemoryManager.build_context() logic.
"""

from __future__ import annotations

import logging
import time

from l1.kernel.params.system import LOG_TRUNC_300

logger = logging.getLogger(__name__)


from l1.kernel.params.system import CONTEXT_BUILD_MAX_TOKENS


def build_context(mem, agent_id: str, max_tokens: int = CONTEXT_BUILD_MAX_TOKENS) -> str:
    """Build an LLM context string from all rings, token-budgeted.

    Context watermarks are injected for traceability.
    """
    from l3.memory.memory_ring import _estimate_tokens

    parts = []
    remaining = max_tokens

    _ctx_id = f"ctx-{int(time.time() * 1000):x}"
    _watermark = (
        f"<!-- WATERMARK: id={_ctx_id} agent={agent_id} "
        f"budget={max_tokens} -->"
    )
    parts.append(_watermark)
    remaining -= len(_watermark)

    w = mem.working.summarize(agent_id)
    if w:
        tok = _estimate_tokens(w)
        if tok <= remaining:
            parts.append("=== Working Memory ===\n" + w)
            remaining -= tok

    s = mem.short.summarize(agent_id)
    if s:
        tok = _estimate_tokens(s)
        if tok <= remaining:
            parts.append("=== Recent History ===\n" + s)
            remaining -= tok

    from l1.kernel.params.system import MEMORY_BUILD_CONTEXT_LIMIT
    l_entries = mem.long.query(agent_id=agent_id, limit=MEMORY_BUILD_CONTEXT_LIMIT)
    if l_entries:
        l_text = "\n".join(f"[{e.entry_type}] {e.content[:LOG_TRUNC_300]}" for e in l_entries)
        tok = _estimate_tokens(l_text)
        if tok <= remaining:
            parts.append("=== Knowledge ===\n" + l_text)

    return "\n\n".join(parts)
