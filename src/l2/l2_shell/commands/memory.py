from __future__ import annotations
import logging, time
from typing import Any
from l1.kernel.params.agent import DEFAULT_CELL_ID
from l1.kernel.params.system import LOG_TRUNC_60, LOG_TRUNC_2000, MEMORY_RECALL_DEFAULT_LIMIT
logger = logging.getLogger(__name__)

def _cmd_memory(args: list[str]) -> dict:
    from .common import resolve_scope, resolve_agents
    scope, scope_id, rest = resolve_scope(args)
    agents = resolve_agents(scope, scope_id)
    if not agents: return {"success": False, "error": "no agents found"}
    op = rest[0].lower() if rest else "search"
    kwargs = {"agent_ids": agents}
    if len(rest) >= 2: kwargs["query"] = " ".join(rest[1:])
    for aid in agents:
        try:
            from l3.memory.memory import get_memory
            mem = get_memory()
            if op == "search": r = mem.recall(agent_id=aid, query=kwargs.get("query", ""), limit=10)
            elif op == "stats": r = mem.aggregate_stats(agent_id=aid)
            else: return {"success": False, "error": f"unknown memory op: {op}"}
            return {"success": True, "agent": aid, "data": r}
        except Exception as e:
            capture("memory: cmd failed", error_code="E_CMD", component="l2", context={"error": str(e)})
            return {"success": False, "error": str(e)}
    return {"success": True}

def _cmd_card(args: list[str]) -> dict:
    from l3.card.card_registry import get_registry
    cr = get_registry()
    if not args: return {"success": True, "data": {"cards": cr.list(state=None)[:10]}}
    sub = args[0].lower()
    if sub == "list": return {"success": True, "data": {"cards": cr.list(state=None)[:20]}}
    if sub == "submit" and len(args) >= 2: return cr.submit(" ".join(args[1:]), ".")
    if sub == "cancel" and len(args) >= 2: return {"success": cr.cancel(args[1])}
    if sub == "approve" and len(args) >= 2: return cr.approve(args[1])
    if sub == "reject" and len(args) >= 2:
        reason = " ".join(args[2:]) if len(args) > 2 else ""
        return cr.reject(args[1], reason=reason)
    return {"success": False, "error": "usage: /card [list|submit <intent>|cancel <id>|approve <id>|reject <id> [reason]]"}

def _cmd_plugins(args: list[str]) -> dict:
    from l3.services.central_plugin import get_center
    center = get_center()
    if args and args[0] == "stats":
        return {"success": True, "stats": center.stats() if hasattr(center, "stats") else {}}
    return {"success": True, "plugins": center.list_plugins() if hasattr(center, "list_plugins") else []}

def _cmd_spawn(args: list[str]) -> dict:
    from l3.cell import get_cell; from l1.kernel.params.agent import DEFAULT_CELL_ID, DEFAULT_CELL_INITIAL_ROLES
    if not args: return {"success": False, "error": "usage: /spawn <name> [role]"}
    name, role = args[0], args[1] if len(args) > 1 else DEFAULT_CELL_INITIAL_ROLES[0]
    cell = get_cell(DEFAULT_CELL_ID); r = cell.add_agent(name, role=role)
    return r

def _cmd_kill(args: list[str]) -> dict:
    if not args: return {"success": False, "error": "usage: /kill <agent_id>"}
    from l3.agent_terminal import get_terminals; terms = get_terminals()
    if args[0] in terms: terms[args[0]].shutdown()
    return {"success": True}

def _cmd_destroy(args: list[str]) -> dict:
    from l3.cell import reset_cells; reset_cells()
    return {"success": True, "message": "all cells reset"}

def _cmd_emergency(args: list[str]) -> dict:
    from l3.cell import get_cell; from l1.kernel.params.agent import DEFAULT_CELL_ID
    cell = get_cell(DEFAULT_CELL_ID); return cell.emergency_stop()

def _cmd_audit(args: list[str]) -> dict:
    from l1.kernel import get_audit_log
    limit = int(args[0]) if args and args[0].isdigit() else 20
    return {"success": True, "audit": get_audit_log(limit=limit)}

def _cmd_cell_create(args: list[str]) -> dict:
    from l3.cell import get_cell
    cell_id = args[0] if args else "cell-new"
    cell = get_cell(cell_id, [args[1] if len(args) > 1 else "."])
    return {"success": True, "cell_id": cell_id}

def _cmd_agent_restart(args: list[str]) -> dict:
    from l3.cell import get_cell; from l1.kernel.params.agent import DEFAULT_CELL_ID
    if not args: return {"success": False, "error": "usage: /agent-restart <agent_id>"}
    cell = get_cell(DEFAULT_CELL_ID); return cell.restart_agent(args[0])

def _cmd_agent_refresh(args: list[str]) -> dict:
    from l3.cell import get_cell; from l1.kernel.params.agent import DEFAULT_CELL_ID
    cell = get_cell(DEFAULT_CELL_ID); return cell.reset_agent_context(args[0]) if args else {"success": False, "error": "agent_id required"}

def _cmd_tokens(args: list[str]) -> dict:
    from l1.kernel.allocator import get_allocator
    alloc = get_allocator()
    if args: return alloc.usage(args[0])
    return alloc.summary()
