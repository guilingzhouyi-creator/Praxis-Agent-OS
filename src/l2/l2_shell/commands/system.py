from __future__ import annotations
import logging, time
logger = logging.getLogger(__name__)

def _cmd_status(args: list[str]) -> dict:
    from l1.kernel import health as _health
    from l1.kernel.process import get_table; from l3.agent_terminal import get_terminals
    h = _health(); print(f"Kernel health: {h['status']} ({h['module_count']} modules)")
    for name, r in h["modules"].items(): print(f"  [{r['status']}] {name}")
    print(f"\nProcesses: {len(get_table().list())}")
    print(f"Terminals: {len(get_terminals())}")
    return h

def _cmd_intents(args: list[str]) -> dict:
    from l3.scheduler.think_registry import get_think_registry
    reg = get_think_registry(); return {"success": True, "intents": reg.list_intents()}

def _cmd_scheduler(args: list[str]) -> dict:
    from l3.scheduler.scheduler import get_scheduler
    s = get_scheduler(); return {"success": True, "data": s.status()}

def _cmd_observe(args: list[str]) -> dict:
    from l3.bus.observability_bus import get_obs_bus
    return {"success": True, "data": get_obs_bus().summary()}

def _cmd_skills(args: list[str]) -> dict:
    from l1.kernel.skill import get_skill_manager; from l1.kernel.params.system import SKILL_LEAN_CASES_LIMIT
    sm = get_skill_manager(); skills = sm.list()
    return {"success": True, "skills": skills[:SKILL_LEAN_CASES_LIMIT], "count": len(skills)}

def _cmd_process(args: list[str]) -> dict:
    from l1.kernel.process import get_table; from l1.kernel.registry import get_registry
    if args and args[0] == "audit": return {"success": True, "audit": get_table().audit_log()}
    return {"success": True, "processes": get_table().list()}

def _cmd_vfs(args: list[str]) -> dict:
    from l1.kernel.vfs import get_vfs
    path = args[0] if args else "/"; r = get_vfs().read(path)
    if r.get("success"): print(r["content"])
    return r

def _cmd_cache(args: list[str]) -> dict:
    from l3.cell import get_cell; from l1.kernel.params.agent import DEFAULT_CELL_ID
    cell = get_cell(DEFAULT_CELL_ID)
    return {"success": True, "cache": cell.cache.stats() if hasattr(cell, 'cache') else {}}

def _cmd_sysinfo(args: list[str]) -> dict:
    import sys; return {"success": True, "python": sys.version, "platform": sys.platform}

def _cmd_clear(args: list[str]) -> dict:
    print("\033[2J\033[H", end=""); return {"success": True}

def _cmd_history(args: list[str]) -> dict:
    from l1.kernel.params.system import SHELL_HISTORY_DEFAULT_LIMIT
    limit = int(args[0]) if args and args[0].isdigit() else SHELL_HISTORY_DEFAULT_LIMIT
    return {"success": True, "history": [], "limit": limit}

def _cmd_lang(args: list[str]) -> dict:
    from l2.i18n import set_locale, get_locale
    if args: set_locale(args[0])
    return {"success": True, "locale": get_locale()}

def _cmd_devices(args: list[str]) -> dict:
    from l1.kernel.device import get_device_manager
    dm = get_device_manager(); devices = dm.list()
    return {"success": True, "devices": devices, "count": len(devices)}

def _cmd_tools(args: list[str]) -> dict:
    from l3.agent_terminal import get_terminals
    agent_id = args[0] if args else ""; terms = get_terminals()
    if agent_id:
        term = terms.get(agent_id)
        if not term: return {"success": False, "error": f"unknown agent: {agent_id}"}
        tools = term.list_tools()
        return {"success": True, "tools": tools, "agent": agent_id}
    return {"terminals": list(terms.keys())}


def _cmd_help(args: list[str]) -> dict:
    """Show help for commands (/help <cmd>) or list all commands."""
    from l1.kernel.commands import get_command
    from l2.l2_shell.commands import list_commands
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
