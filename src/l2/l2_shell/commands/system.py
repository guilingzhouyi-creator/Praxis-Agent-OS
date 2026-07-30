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
