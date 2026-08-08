"""API handler mixin — L2 shell session-state endpoint.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def session_state(body: dict | None = None) -> dict:
    """Current L2 shell state (mode / agent / cell / direct flag)."""
    from l2.l2_shell import get_state

    s = get_state()
    return {"mode": s.mode, "agent_id": s.agent_id or "", "cell_id": s.cell_id, "is_direct": s.is_direct()}
