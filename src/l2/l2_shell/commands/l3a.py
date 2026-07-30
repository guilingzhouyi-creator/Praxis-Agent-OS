"""L2 Shell: L3A session management commands.

Routes `/l3a` to the L3A daemon dispatch.
"""

from __future__ import annotations

from l3.cell.peers.l3a import dispatch as _l3a_dispatch

_l3a_initialized = False


def _ensure() -> None:
    global _l3a_initialized
    if not _l3a_initialized:
        from l3.cell.peers.l3a import start
        start()
        _l3a_initialized = True


def _cmd_l3a(args: list[str]) -> dict:
    _ensure()
    return _l3a_dispatch(args)
