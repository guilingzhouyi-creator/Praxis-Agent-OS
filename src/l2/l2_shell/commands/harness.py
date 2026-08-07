"""L2 Shell: harness mode command (harness)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _cmd_harness(args: list[str]) -> dict:
    """Show or switch the harness mode (governed / semi / minimal)."""
    from l3.tool_system.harness import (
        harness_status,
        reset_harness_mode,
        set_harness_mode,
    )

    if not args:
        return {"success": True, **harness_status()}
    sub = args[0].lower()
    if sub == "reset":
        return {"success": True, **reset_harness_mode()}
    if sub in ("governed", "semi", "minimal"):
        confirm = "--confirm" in args or "-y" in args
        return set_harness_mode(sub, confirmed=confirm, source="shell")
    if sub in ("--confirm", "-y"):
        return {"success": False, "error": "usage: /harness <governed|semi|minimal> [--confirm]"}
    return {"success": False, "error": f"unknown harness mode: {sub}"}
