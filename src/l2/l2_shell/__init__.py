"""Shell (L2) — human interface layer with command dispatch, mode switching,
output guard, and auto-completion.

Sub-modules:
  state       — ShellState singleton
  completer   — autocomplete, _complete_agent, _complete_role
  output_guard — guard_output, set_output_guard
  commands    — all _cmd_* handlers, _pipeline, preconnect_enhanced
"""

from __future__ import annotations

import logging
import shlex

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.commands import get_command, get_handler, get_registry as _get_cmd_reg
from l1.kernel.params.agent import DEFAULT_CELL_ID, SIGNAL_TARGET_L3

from .commands import (
    preconnect_enhanced, _pipeline, list_commands,
    _cmd_connect, _cmd_disconnect, _cmd_mode, _cmd_agents, _cmd_help,
    _cmd_status, _cmd_intents, _cmd_scheduler, _cmd_observe,
    _cmd_skills, _cmd_memory, _cmd_plugins, _cmd_security,
    _cmd_cells, _cmd_cross,
)
from .completer import autocomplete, _complete_role, _complete_agent  # noqa: F401
from .output_guard import guard_output, set_output_guard  # noqa: F401
from .state import get_state, reset_state, ShellState  # noqa: F401

logger = logging.getLogger(__name__)

# ── Alias reverse index (built once, refreshed on registry change) ──
_ALIAS_REVERSE_INDEX: dict[str, str] = {}
_ALIAS_INDEX_STALE: bool = True


def _rebuild_alias_index() -> None:
    """Build a reverse index mapping alias → command name."""
    global _ALIAS_REVERSE_INDEX, _ALIAS_INDEX_STALE
    idx: dict[str, str] = {}
    for c in _get_cmd_reg().list():
        for alias in c.get("aliases", []):
            idx[alias] = c["name"]
    _ALIAS_REVERSE_INDEX = idx
    _ALIAS_INDEX_STALE = False


def _lookup_alias(alias: str) -> str | None:
    """Resolve an alias to its canonical command name."""
    global _ALIAS_INDEX_STALE
    if _ALIAS_INDEX_STALE:
        _rebuild_alias_index()
    return _ALIAS_REVERSE_INDEX.get(alias)


def dispatch(text: str) -> dict:
    """Route user input to the active shell mode.

    Parser order:
      1. ``|`` in text → pipeline (``_pipeline``)
      2. ``/`` prefix  → shell command (CommandRegistry lookup)
      3. Direct mode active → ``_direct_message``
      4. Default → ``_l3a_intent`` (L3A natural language processing)
    """
    if "|" in text:
        segments = [s.strip() for s in text.split("|")]
        if len(segments) >= 2:
            return _pipeline(segments)

    state = get_state()

    if text.startswith("/"):
        parts = shlex.split(text)
        cmd = parts[0][1:]
        args = parts[1:]
        info = get_command(cmd)
        if info:
            handler = get_handler(cmd)
            if handler:
                return handler(args)
        # Check aliases via reverse index (O(1) instead of O(n))
        resolved = _lookup_alias(cmd)
        if resolved:
            handler = get_handler(resolved)
            if handler:
                return handler(args)
        try:
            from l2.i18n import t as _t
            err = _t("shell.error.unknown_command", cmd=cmd)
        except Exception:
            logger.warning("i18n translation failed for shell.error.unknown_command")
            err = f"unknown command: /{cmd}"
        return {"success": False, "error": err,
                "suggestions": [c["name"] for c in _get_cmd_reg().list()]}

    if state.is_direct():
        return _direct_message(state, text)

    return _l3a_intent(text)


def _direct_message(state: ShellState, text: str) -> dict:
    """Send a direct message to the currently connected agent.

    On failure, automatically disconnects and falls back to L3A mode.
    Passes the response through ``guard_output``.
    """
    try:
        from l3.cell import get_cell
        cell = get_cell(state.cell_id)
        r = cell.send_direct_message(state.agent_id, text)
        if not r.get("success"):
            _auto_disconnect(state, r.get("error", "send_failed"))
            return r
        response = r.get("output", r.get("answer", ""))
        guarded = guard_output(state.agent_id, response)
        r["raw_answer"] = response
        r["answer"] = guarded["output"]
        r["output_guarded"] = not guarded["safe"]
        return r
    except Exception as e:
        _auto_disconnect(state, str(e))
        return {"success": False, "error": str(e)}


def _auto_disconnect(state: ShellState, reason: str) -> None:
    """Auto-disconnect from Direct mode on error and fall back to L3A.

    Emits ``EVENT_TASK_ASSIGN`` so the L3 coordinator knows the mode changed.
    """
    if not state.is_direct():
        return
    logger.warning("auto-disconnect from %s: %s", state.agent_id, reason)
    try:
        from l3.cell import get_cell
        cell = get_cell(state.cell_id)
        cell.close_direct_session(state.agent_id)
    except Exception:
        logger.warning("auto-disconnect: close_direct_session failed for %s", state.agent_id)
    state.switch_to_l3a()
    emit_signal(EVENT_TASK_ASSIGN, sender="shell", target=SIGNAL_TARGET_L3,
                 data={"event": "l3a_mode_restored_auto", "reason": reason})


def _l3a_intent(text: str) -> dict:
    """Send a natural-language intent to the L3 coordinator for processing."""
    try:
        from .cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        return coord.process_intent(text)
    except Exception as e:
        return {"success": False, "error": str(e)}
