"""Terminal lifecycle helpers — extracted from agent_terminal.py for modularity."""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_KEEPALIVE_INTERVAL: float = 240.0
CACHE_KEEPALIVE_PROMPT: str = "keepalive"


def run_cache_keepalive(term: Any) -> None:
    """Background thread: refresh LLM KV cache TTL during idle periods.
    
    Skip entirely when LLM is in mock mode (testing).
    """
    from .llm import get_engine
    from .llm_base import list_providers
    providers = list_providers()
    if "mock" in providers and len(providers) == 1:
        return  # mock mode — no keepalive needed
    while term._running:
        time.sleep(CACHE_KEEPALIVE_INTERVAL)
        if not term._running:
            break
        with term._lock:
            if term.status.name != "IDLE":
                continue
        try:
            from kernel.prompts import get_prompt as _get_prompt
            engine = get_engine()
            result = engine.generate_with_cache(
                prompt=CACHE_KEEPALIVE_PROMPT,
                system=_get_prompt("agent_loop.keepalive").format(
                    agent_id=term.agent_id, role=term.role,
                ),
                max_tokens=1,
                user_id=term.agent_id,
            )
            if result.get("cache_hit_rate", 0) < 50:
                logger.warning("keepalive cache miss for %s: hit_rate=%.1f%%",
                               term.agent_id, result.get("cache_hit_rate", 0))
        except Exception:
            pass
