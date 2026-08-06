"""Terminal lifecycle helpers — extracted from agent_terminal.py for modularity."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from l1.kernel.params.agent import (  # noqa: E402  (mid-file import avoids circularity)
    CACHE_KEEPALIVE_INTERVAL,
    CACHE_KEEPALIVE_PROMPT,
    KEEPALIVE_CACHE_HIT_MIN,
    KEEPALIVE_MAX_TOKENS,
)


def run_cache_keepalive(term: Any) -> None:
    """Background thread: refresh LLM KV cache TTL during idle periods.

    Skip entirely when LLM is in mock mode (testing).
    """
    from l4.llm.llm import get_engine
    from l4.llm.llm_base import list_providers

    providers = list_providers()
    if "mock" in providers and len(providers) == 1:
        return  # mock mode — no keepalive needed
    while term._running:
        time.sleep(CACHE_KEEPALIVE_INTERVAL)
        if not term._running:
            break
        with term._lock:
            from l1.kernel.params.agent import AGENT_STATUS_IDLE

            if term.status.name != AGENT_STATUS_IDLE:
                continue
        try:
            from l1.kernel.prompts import get_prompt as _get_prompt

            engine = get_engine()
            result = engine.generate_with_cache(
                prompt=CACHE_KEEPALIVE_PROMPT,
                system=_get_prompt("agent_loop.keepalive").format(
                    agent_id=term.agent_id,
                    role=term.role,
                ),
                max_tokens=KEEPALIVE_MAX_TOKENS,
                user_id=term.agent_id,
            )
            if result.get("cache_hit_rate", 0) < KEEPALIVE_CACHE_HIT_MIN:
                logger.warning(
                    "keepalive cache miss for %s: hit_rate=%.1f%%", term.agent_id, result.get("cache_hit_rate", 0)
                )
        except Exception:
            logger.debug("_term_lifecycle: keepalive check failed")
