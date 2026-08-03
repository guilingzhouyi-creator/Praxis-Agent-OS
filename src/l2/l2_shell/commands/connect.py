from __future__ import annotations
import logging
from l2.selector import preselect
logger = logging.getLogger(__name__)

def _cmd_help(args: list[str]) -> dict:
    from l1.kernel.commands import get_command; from .common import list_commands
    try:
        if args:
            cmd_name = args[0].lower().lstrip("/"); cmd = get_command(cmd_name)
            if not cmd: return {"success": False, "error": f"unknown command: {cmd_name}"}
            lines = [f"/{cmd_name}  — {cmd.get('help', '')}"]
            if cmd.get("aliases"): lines.append(f"  aliases: {', '.join('/' + a for a in cmd['aliases'])}")
            if cmd.get("args"):
                lines.append("  args:")
                for a in cmd["args"]:
                    opt = " (optional)" if a.get("optional") else ""; lines.append(f"    {a['name']}{opt} — {a.get('description', '')}")
            if cmd.get("examples"):
                lines.append("  examples:")
                for e in cmd["examples"]: lines.append(f"    {e}")
            lines.append(f"  category: {cmd.get('category', 'other')}"); return {"success": True, "output": "\n".join(lines), "format": "table"}
        cmds = list_commands(); groups = {}
        for c in cmds: groups.setdefault(c.get("category", "other"), []).append(c)
        cat_labels = {"session": "Session", "control": "Central Control", "memory": "Memory", "system": "System", "agent": "Agent / Cell", "audit": "Audit / Config", "ext": "Extensions"}
        lines = ["Available commands:", ""]
        for cat in ["session", "control", "memory", "system", "agent", "audit", "ext"]:
            items = groups.get(cat, []); items = groups.get(cat, [])
            if not items: continue
            lines.append(f"  ── {cat_labels.get(cat, cat)} ──")
            for c in items:
                alias_str = f" ({', '.join('/' + a for a in c['aliases'])})" if c.get("aliases") else ""
                lines.append(f"    {c['command']:25s} {c.get('help', '')}{alias_str}")
            lines.append("")
        lines.append("  Tip: /help <command> for details & examples")
        return {"success": True, "output": "\n".join(lines), "format": "table"}
    except Exception as e: return {"success": False, "error": str(e)}

def _cmd_agents(args: list[str]) -> dict:
    try: return {"success": True, "data": preselect()}
    except Exception as e: return {"success": False, "error": str(e)}

def _cmd_connect(args: list[str]) -> dict:
    from l3.agent_terminal import get_terminals
    if not args: return {"success": False, "error": "usage: /connect <agent_id>"}
    from l3.cell import get_cell; from ..state import get_state; from l1.kernel.params.agent import DEFAULT_CELL_ID
    agent_id = args[0]; terms = get_terminals()
    if agent_id not in terms: return {"success": False, "error": f"unknown agent: {agent_id}"}
    state = get_state(); cell_id = DEFAULT_CELL_ID
    try:
        cell = get_cell(cell_id); r = cell.send_direct_message(agent_id, "")
        if not r.get("success"): return {"success": False, "error": r.get("error", "connect failed")}
    except Exception: pass
    state.switch_to_direct(cell_id, agent_id)
    return {"success": True, "agent": agent_id}

def _cmd_disconnect(args: list[str]) -> dict:
    from ..state import get_state
    state = get_state()
    if not state.is_direct(): return {"success": False, "error": "no active session — not connected"}
    try:
        from l3.cell import get_cell; cell = get_cell(state.cell_id); cell.close_direct_session(state.agent_id)
    except Exception: pass
    state.switch_to_l3a(); return {"success": True}

def _cmd_mode(args: list[str]) -> dict:
    from ..state import get_state
    state = get_state()
    if args:
        sub = args[0].lower()
        if sub == "direct":
            if not state.agent_id:
                return {"success": False, "error": "no agent connected — use /connect first"}
            state.switch_to_direct(state.cell_id, state.agent_id)
            return {"success": True, "mode": "DIRECT", "cell_id": state.cell_id,
                    "current_tool_mode": "read"}
        if sub == "tool":
            tool_mode = args[1].lower() if len(args) > 1 else "toggle"
            current = "write" if tool_mode == "write" else "read"
            return {"success": True, "mode": state.mode, "cell_id": state.cell_id,
                    "current_tool_mode": current}
        return {"success": False, "error": f"unknown mode subcommand: {sub}"}
    return {"success": True, "mode": state.mode, "cell_id": state.cell_id,
            "current_tool_mode": "read"}
