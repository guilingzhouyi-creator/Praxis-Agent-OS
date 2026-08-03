"""Adapter bridge — thin L3 wrappers for L4 services.

Eliminates L2→L4 direct imports by providing L3 service wrappers
that L2 shell commands call instead of importing L4 directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_llm_engine():
    """Get the LLM engine instance (wraps l4.llm.llm.get_engine)."""
    from l4.llm.llm import get_engine
    return get_engine()


def get_mcp_bridge():
    """Get the MCP bridge and client (wraps l4.mcp_bridge)."""
    from l4.mcp_bridge import McpClient, get_bridge  # noqa: F401
    return get_bridge(), McpClient


def get_cron_scheduler():
    """Get the cron scheduler (wraps l4.cron_scheduler)."""
    from l4.cron_scheduler import get_scheduler
    return get_scheduler()


def export_vault_status() -> dict:
    """Export vault credential status (wraps l4.vault.credential_vault)."""
    from l4.vault.credential_vault import export_vault_status
    return export_vault_status()
