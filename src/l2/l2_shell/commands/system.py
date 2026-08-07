"""L2 Shell: system commands (status, devices, process, history, lang, clear, help)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _cmd_status(args: list[str]) -> dict:
    from l1.kernel.healthcheck import safe_system_check as _health
    from l1.kernel.process import get_table
    from l3.agent_terminal import get_terminals

    h = _health()
    print(f"Kernel health: {h.get('status', '?')} ({h.get('module_count', 0)} modules)")
    for name, r in h.get("subsystems", {}).items():
        print(f"  [{r['status']}] {name}")
    print(f"\nProcesses: {len(get_table().list_processes())}")
    print(f"Terminals: {len(get_terminals())}")
    try:
        from l1.kernel.lifecycle import get_lifecycle

        lc = get_lifecycle()
        rec = lc.load()
        print(f"Lifecycle: {lc.state().value} (boots={rec.boot_count}, schema={rec.schema_version or 'unset'})")
    except Exception:
        logger.debug("system: lifecycle load failed, skipping", exc_info=True)
    # Enrich with shell mode/cell context (agent_id only present in Direct mode)
    result = dict(h)
    try:
        from ..state import get_state

        st = get_state()
        result["mode"] = st.mode
        result["cell_id"] = st.cell_id
        if st.is_direct():
            result["agent_id"] = st.agent_id
    except Exception:
        logger.debug("system: shell state enrichment failed", exc_info=True)
    return result


def _cmd_intents(args: list[str]) -> dict:
    from l3.scheduler.think_registry import get_think_registry

    reg = get_think_registry()
    return {"success": True, "intents": reg.stats()}


def _cmd_scheduler(args: list[str]) -> dict:
    from l3.scheduler.scheduler import get_scheduler

    s = get_scheduler()
    return {"success": True, "data": s.stats() if hasattr(s, "stats") else {}}


def _cmd_observe(args: list[str]) -> dict:
    from l3.bus.observability_bus import get_obs_bus

    return {"success": True, "data": get_obs_bus().summary()}


def _cmd_skills(args: list[str]) -> dict:
    """Manage skills — list/get are public; create/update/delete/reload are developer-only.

    Usage:
      /skills                          → list skills
      /skills list                     → list skills
      /skills lean                     → list lean case skills
      /skills get <name>               → skill detail
      /skills create <name> <desc> <prompt> [--role <role>]
      /skills update <name> <field> <value> [--role <role>]
      /skills delete <name> [--role <role>]
      /skills reload [--role <role>]
      /skills evolve <intent>          → generate a new skill via LLM
      /skills permissions              → current write-gate policy
      /skills distill [status]        → distillation/DPO master switches
      /skills distill set <field> <on|off>  → toggle distill|dpo_signal at runtime
      /skills retriever [status]       → active retrieval backend (tfidf|embedding)
      /skills retriever set <backend>  → switch retrieval backend at runtime

    The optional ``--role``/``--agent`` flag supplies the caller identity for
    the SkillManager developer gate; omitting it treats the call as a
    system-internal (boot/CLI) operation.
    """
    from l1.kernel.params.system import SKILL_LIST_DISPLAY_LIMIT
    from l1.kernel.skill import get_skill_manager

    sm = get_skill_manager()

    role = ""
    agent_id = ""
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--role", "--agent") and i + 1 < len(args):
            if a == "--role":
                role = args[i + 1]
            else:
                agent_id = args[i + 1]
            i += 2
        else:
            rest.append(a)
            i += 1

    sub = rest[0] if rest else "list"

    if sub in ("list", "ls"):
        skills = sm.list_skills()
        return {"success": True, "skills": skills[:SKILL_LIST_DISPLAY_LIMIT], "count": len(skills)}

    if sub == "lean":
        skills = sm.list_skills(tags=["lean_case"])
        return {"success": True, "skills": skills[:SKILL_LIST_DISPLAY_LIMIT], "count": len(skills)}

    if sub == "get":
        name = rest[1] if len(rest) > 1 else ""
        if not name:
            return {"success": False, "error": "usage: /skills get <name>"}
        skill = sm.get(name)
        if not skill:
            return {"success": False, "error": f"skill '{name}' not found"}
        return {"success": True, "skill": skill}

    if sub == "permissions":
        # Policy lives on the SkillManager (L1) — L2 must not import L3.
        policy = sm.write_policy()
        return {"success": True, "policy": policy}

    if sub == "distill":
        # Distillation / DPO master switches (same state as
        # /api/v2/skills/distill-policy). Status is public; toggling is a
        # developer runtime knob.
        action = rest[1] if len(rest) > 1 else "status"
        if action == "status":
            return {"success": True, "policy": sm.distill_policy()}
        if action in ("set", "on", "off"):
            field = rest[2] if len(rest) > 2 else ""
            value = rest[3] if len(rest) > 3 else ""
            if field not in ("distill", "dpo_signal") or value not in ("on", "off", "true", "false", "1", "0"):
                return {
                    "success": False,
                    "error": "usage: /skills distill set <distill|dpo_signal> <on|off>",
                }
            flag = value in ("on", "true", "1")
            if field == "distill":
                return sm.set_distill_policy(distill=flag)
            return sm.set_distill_policy(dpo_signal=flag)
        return {
            "success": False,
            "error": f"unknown distill action: {action}",
            "suggestions": ["status", "set <distill|dpo_signal> <on|off>"],
        }

    if sub == "retriever":
        # Skill retriever backend control (tfidf | embedding).  Read-only
        # status is public; switching backend is a runtime knob like
        # /api/v2/skills/retriever (same state, two surfaces).
        action = rest[1] if len(rest) > 1 else "status"
        from l3.memory.skill_retriever import retriever_status, set_backend

        if action == "status":
            return retriever_status()
        if action == "set":
            backend = rest[2] if len(rest) > 2 else ""
            if not backend:
                return {"success": False, "error": "usage: /skills retriever set <tfidf|embedding>"}
            return set_backend(backend)
        return {
            "success": False,
            "error": f"unknown retriever action: {action}",
            "suggestions": ["status", "set <tfidf|embedding>"],
        }

    if sub == "evolve":
        intent = " ".join(rest[1:])
        if not intent:
            return {"success": False, "error": "usage: /skills evolve <intent>"}
        # evolve persists a new skill to disk — honor the developer write gate
        # like create/update/delete/reload (see authorize_write in SkillManager).
        ok, who = sm.authorize_write(agent_id, role)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        try:
            from l3.memory.r4_agent import get_r4_agent

            return get_r4_agent().evolve_skill(intent)
        except Exception as e:
            return {"success": False, "error": f"evolve failed: {e}"}

    # ── Developer-only mutations ──
    if sub == "create":
        if len(rest) < 4:
            return {"success": False, "error": "usage: /skills create <name> <desc> <prompt> [--role <role>]"}
        name, desc, prompt = rest[1], rest[2], rest[3]
        return sm.create(name, description=desc, prompt=prompt, agent_id=agent_id, role=role)

    if sub == "update":
        if len(rest) < 4:
            return {"success": False, "error": "usage: /skills update <name> <field> <value> [--role <role>]"}
        name, field, value = rest[1], rest[2], rest[3]
        if field not in ("description", "prompt", "rules"):
            return {"success": False, "error": f"unsupported field: {field}"}
        data: dict[str, object] = {"rules": [r for r in value.split(";") if r]} if field == "rules" else {field: value}
        return sm.update(name, data, agent_id=agent_id, role=role)

    if sub == "delete":
        name = rest[1] if len(rest) > 1 else ""
        if not name:
            return {"success": False, "error": "usage: /skills delete <name> [--role <role>]"}
        return sm.delete(name, agent_id=agent_id, role=role)

    if sub == "reload":
        ok, who = sm.authorize_write(agent_id, role)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        count = sm.load_builtin()
        return {"success": True, "loaded": count, "authorized": who}

    return {
        "success": False,
        "error": f"unknown skills subcommand: {sub}",
        "suggestions": ["list", "get", "create", "update", "delete", "reload", "permissions"],
    }


def _cmd_process(args: list[str]) -> dict:
    from l1.kernel.process import get_table

    if args and args[0] == "audit":
        return {"success": True, "audit": get_table().audit_log()}
    return {"success": True, "processes": get_table().list_processes()}


def _cmd_vfs(args: list[str]) -> dict:
    from l1.kernel.vfs import get_vfs

    path = args[0] if args else "/"
    r = get_vfs().read(path)
    if r.get("success"):
        print(r["content"])
    return r


def _cmd_cache(args: list[str]) -> dict:
    from l1.kernel.params.agent import DEFAULT_CELL_ID
    from l3.cell import get_cell

    cell = get_cell(DEFAULT_CELL_ID)
    return {"success": True, "cache": cell.cache.stats() if hasattr(cell, "cache") else {}}


def _cmd_sysinfo(args: list[str]) -> dict:
    import sys

    return {"success": True, "python": sys.version, "platform": sys.platform}


def _cmd_clear(args: list[str]) -> dict:
    print("\033[2J\033[H", end="")
    return {"success": True, "clear": True}


def _cmd_history(args: list[str]) -> dict:
    from l1.kernel.params.system import SHELL_HISTORY_DEFAULT_LIMIT

    limit = int(args[0]) if args and args[0].isdigit() else SHELL_HISTORY_DEFAULT_LIMIT
    return {"success": True, "history": [], "limit": limit}


def _cmd_lang(args: list[str]) -> dict:
    from l2.i18n import get_available_locales, get_locale, set_locale

    if args:
        set_locale(args[0])
    return {"success": True, "locale": get_locale(), "available": get_available_locales()}


def _cmd_devices(args: list[str]) -> dict:
    from l1.kernel.device import get_device_manager

    dm = get_device_manager()
    devices = dm.list()
    return {"success": True, "devices": devices, "count": len(devices)}


def _cmd_tools(args: list[str]) -> dict:
    from l3.agent_terminal import get_terminals

    agent_id = args[0] if args else ""
    terms = get_terminals()
    if agent_id:
        term = terms.get(agent_id)
        if not term:
            return {"success": False, "error": f"unknown agent: {agent_id}"}
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
        return {"success": True, "output": "\n".join(lines), "format": "table"}
    cmds = list_commands()
    groups: dict[str, list] = {}
    for c in cmds:
        cat = c.get("category", "other")
        groups.setdefault(cat, []).append(c)
    cat_labels = {
        "session": "Session",
        "control": "Central Control",
        "memory": "Memory",
        "system": "System",
        "agent": "Agent / Cell",
        "audit": "Audit / Config",
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
    return {"success": True, "output": "\n".join(lines), "format": "table"}
