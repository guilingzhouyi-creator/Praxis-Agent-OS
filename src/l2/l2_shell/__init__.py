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
from l1.kernel.params.agent import DEFAULT_CELL_ID

from .commands import preconnect_enhanced, _pipeline
from .completer import autocomplete  # noqa: F401
from .output_guard import guard_output, set_output_guard  # noqa: F401
from .state import get_state, reset_state, ShellState  # noqa: F401

logger = logging.getLogger(__name__)


def dispatch(text: str) -> dict:
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
        # Check aliases
        for c in _get_cmd_reg().list():
            if cmd in c.get("aliases", []):
                handler = get_handler(c["name"])
                if handler:
                    return handler(args)
                break
        try:
            from l2.i18n import t as _t
            err = _t("shell.error.unknown_command", cmd=cmd)
        except Exception:
            err = f"unknown command: /{cmd}"
        return {"success": False, "error": err,
                "suggestions": [c["name"] for c in _get_cmd_reg().list()]}

    if state.is_direct():
        return _direct_message(state, text)

    return _l3a_intent(text)


def _direct_message(state: ShellState, text: str) -> dict:
    try:
        from .cell import get_cell
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
    if not state.is_direct():
        return
    logger.warning("auto-disconnect from %s: %s", state.agent_id, reason)
    try:
        from .cell import get_cell
        cell = get_cell(state.cell_id)
        cell.close_direct_session(state.agent_id)
    except Exception:
        pass
    state.switch_to_l3a()
    emit_signal(EVENT_TASK_ASSIGN, sender="shell", target="l3",
                 data={"event": "l3a_mode_restored_auto", "reason": reason})


def _l3a_intent(text: str) -> dict:
    try:
        from .l3 import get_coordinator
        coord = get_coordinator()
        return coord.process_intent(text)
    except Exception as e:
        return {"success": False, "error": str(e)}
