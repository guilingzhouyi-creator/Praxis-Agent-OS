from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

def _cmd_help(args: list[str]) -> dict:
    if args:
        cmd_name = args[0].lower().lstrip("/")
        cmd = get_command(cmd_name)
        if not cmd:
            return {"success": False, "error": f"unknown command: {cmd_name}"}
        lines = [f"/{cmd_name}  — {cmd.get('help', '')}"]
        if cmd.get("aliases"):
            lines.append(f"  aliases: {', '.join('/' + a for a in cmd['aliases'])}")
        if cmd.get("args"):
            lines.append("  args:")
            for a in cmd["args"]:
                opt = " (optional)" if a.get("optional") else ""
                lines.append(f"    {a['name']}{opt} — {a.get('description', '')}")
        if cmd.get("examples"):
            lines.append("  examples:")
            for e in cmd["examples"]:
                lines.append(f"    {e}")
        lines.append(f"  category: {cmd.get('category', 'other')}")
        return {"success": True, "output": "\n".join(lines), "format": "text"}

    cmds = list_commands()
    groups = {}
    for c in cmds:
        cat = c.get("category", "other")
        groups.setdefault(cat, []).append(c)
    cat_labels = {
        "session": "Session", "control": "Central Control", "memory": "Memory",
        "system": "System", "agent": "Agent / Cell", "audit": "Audit / Config",
        "ext": "Extensions",
    }
    lines = ["Available commands:", ""]
    for cat in ["session", "control", "memory", "system", "agent", "audit", "ext"]:
        items = groups.get(cat, [])
        if not items:
            continue
        label = cat_labels.get(cat, cat)
        lines.append(f"  ── {label} ──")
        for c in items:
            name = c.get("command", "")
            help_text = c.get("help", "")
            alias_str = ""
            if c.get("aliases"):
                alias_str = f" ({', '.join('/' + a for a in c['aliases'])})"
            lines.append(f"    {name:25s} {help_text}{alias_str}")
        lines.append("")
    lines.append("  Tip: /help <command> for details & examples")
    lines.append("  Tip: cmd1 | cmd2 for pipeline (auto Map/Chain/Passthrough)")
    lines.append("  Tip: --cell or --agent for scoped operations")
    return {"success": True, "output": "\n".join(lines), "format": "text"}

def _cmd_agents(args: list[str]) -> dict:
    from l2.selector import preselect
    return preselect()

def _cmd_connect(args: list[str]) -> dict:
    from .state import get_state
    if not args:
        return {"success": False, "error": "usage: /connect <agent_id>"}
    agent_id = args[0]
    state = get_state()
    cell_id = state.cell_id
    try:
        from l3.services.central_security import get_center as _get_sec
        sec = _get_sec().check_all(
            action="direct_session", agent_id=agent_id, target=cell_id,
            tool_name="direct_message",
        )
        if not sec.get("allowed"):
            return {"success": False, "error": "connect blocked by security", "security": sec}
    except Exception as e:
        logger.warning("security check unavailable: %s", e)
        return {"success": False, "error": f"security check required but unavailable: {e}"}
    check = preconnect_enhanced(cell_id, agent_id)
    if not check.get("allowed"):
        return {"success": False, "error": f"connect failed: {check.get('reason')}",
                "checks": check.get("checks", {})}
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        r = cell.send_direct_message(agent_id, "Hello")
        if r.get("success"):
            state.switch_to_direct(cell_id, agent_id)
            emit_signal(EVENT_TASK_ASSIGN, sender="shell", target="l3",
                         data={"event": "direct_mode_entered",
                               "cell_id": cell_id, "agent_id": agent_id})
            return {"success": True, "message": f"Connected to {agent_id}",
                    "card_id": r.get("card_id", ""),
                    "checks": check.get("checks", {})}
        return {"success": False, "error": r.get("error", "send_failed")}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_disconnect(args: list[str]) -> dict:
    from .state import get_state
    state = get_state()
    if not state.is_direct():
        return {"success": False, "error": "no active direct session"}
    try:
        from l3.cell import get_cell
        cell = get_cell(state.cell_id)
        r = cell.close_direct_session(state.agent_id)
        state.switch_to_l3a()
        emit_signal(EVENT_TASK_ASSIGN, sender="shell", target="l3",
                     data={"event": "l3a_mode_restored"})
        return {"success": True, "message": "Disconnected, returned to L3A mode"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_mode(args: list[str]) -> dict:
    from .state import get_state
    state = get_state()
    tool_mode = state.mode
    result = {"mode": tool_mode, "agent_id": state.agent_id or "-", "cell_id": state.cell_id}
    if args:
        from l3.tool_system.tool_mode import set_mode, get_mode
        if args[0] == "tool":
            sub = args[1] if len(args) > 1 else "toggle"
            sr = set_mode(sub)
            result["tool_mode"] = sr
            result["current_tool_mode"] = get_mode()
        else:
            result["error"] = "usage: /mode [tool [read|write|toggle]]"
    else:
        from l3.tool_system.tool_mode import get_mode
        result["current_tool_mode"] = get_mode()
    return result

def _cmd_status(args: list[str]) -> dict:
    from .state import get_state
    state = get_state()
    result = {"mode": state.mode, "cell_id": state.cell_id}
    if state.is_direct():
        result["agent_id"] = state.agent_id
        result["session_id"] = state.session_id
        try:
            from l3.cell import get_cell
            cell = get_cell(state.cell_id)
            result["liveness"] = cell.liveness()
        except Exception as e:
            result["liveness_error"] = str(e)
    return result

