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


def _cmd_agents_md(args: list[str]) -> dict:
    """Generate/refresh the project handbook (AGENTS.md) via the L3A pipeline.

    Thin shell command: routes ``agents-md`` into the L3A dispatch, which
    runs collect → assemble → sandbox write → (optional) generalize.
    ``--no-evolve`` skips the R4Agent skill distillation step.
    """
    _ensure()
    return _l3a_dispatch(["agents-md"] + args)
