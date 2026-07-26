"""CLI commands — extracted from main.py for modularity."""
from __future__ import annotations

import time
import sys


def cmd_boot(args):
    from l1.kernel.os import get_os
    from l1.kernel.params.agent import TERRITORY_PATHS, TERRITORY_MAP
    agent_config = []
    for role, paths in TERRITORY_PATHS.items():
        agent_config.append((f"agent-{role}", role, paths))
    if not agent_config:
        agent_config = [("agent-default", "default", ["."])]
        TERRITORY_MAP["."] = "default"
    osys = get_os()
    r = osys.boot(agent_config)
    if r.get("success"):
        osys.watchdog_start()
        print(f"Boot OK in {r['elapsed']}s")
        print(f"  Cell: {r.get('cell_id','cell-1')}")
        print(f"  Agents: {len(r.get('agents', []))}")
        for a in r.get("agents", []):
            print(f"    {a}")
    else:
        print(f"Boot FAILED: {r.get('results', {})}")
    return r


def cmd_health(args):
    from l1.kernel import health
    h = health()
    print(f"Kernel health: {h['status']} ({h['module_count']} modules)")
    for name, r in h["modules"].items():
        status = r["status"]
        elapsed = r.get("elapsed_ms", 0)
        error = f" — {r['error']}" if "error" in r else ""
        print(f"  [{status}] {name:15s} {elapsed:>5}ms{error}")
    return h


def cmd_ps(args):
    from l1.kernel.process import get_table
    procs = get_table().list()
    if not procs:
        print("No processes")
        return {"processes": []}
    print(f"{'PID':>4} {'NAME':20s} {'ROLE':15s} {'STATE':12s} {'RING':>4} {'UPTIME':>8}")
    print("-" * 70)
    for p in procs:
        print(f"{p['pid']:>4} {p['name']:20s} {p['role']:15s} {p['state']:12s} {p['ring']:>4} {p['uptime']:>7}s")
    return {"processes": procs}


def cmd_card(args):
    if not args:
        print("Usage: card <intent> [domain]")
        return {"success": False, "error": "intent required"}
    intent = " ".join(args)
    domain = "."
    from l3.cell import get_cell, reset_cells
    from l3.agent_terminal import reset_terminals
    cell = get_cell("shell-cell", [domain])
    t0 = time.time()
    result = cell.execute_card(intent, domain=domain)
    elapsed = time.time() - t0
    steps = result.get("steps", [])
    ok = sum(1 for s in steps if s.get("success"))
    print(f"Card: {ok}/{len(steps)} steps in {elapsed:.3f}s")
    for s in steps:
        v = ""
        if s.get("verify"):
            v = f" verify={s['verify'].get('pass','?')}"
        print(f"  [{s.get('success','?')}] {s.get('action','?'):12s} {str(s.get('target',''))[:30]:30s} {s.get('agent',''):15s} {s.get('elapsed',0):.3f}s{v}")
    return result


def cmd_tools(args):
    from l3.agent_terminal import get_terminals
    agent_id = args[0] if args else ""
    terms = get_terminals()
    if agent_id:
        term = terms.get(agent_id)
        if not term:
            print(f"Unknown agent: {agent_id}")
            return {"tools": []}
        tools = term.list_tools()
        print(f"Tools for {agent_id} (ring {term.ring}): {len(tools)}")
        for t in tools:
            print(f"  [{t['ring']:8s}] {t['name']:25s} danger={t['danger']}  {t.get('description','')[:50]}")
        return {"tools": tools, "agent": agent_id}
    for aid, term in sorted(terms.items()):
        tools = term.list_tools()
        if tools:
            print(f"  {aid} (ring {term.ring}): {len(tools)} tools")
    return {"terminals": list(terms.keys())}


def cmd_audit(args):
    from l1.kernel import get_audit_log
    from l1.kernel.params.kernel import SYSCALL_AUDIT_CLI_LIMIT
    agent_filter = args[0] if args else ""
    logs = get_audit_log(limit=SYSCALL_AUDIT_CLI_LIMIT, agent_id=agent_filter)
    if not logs:
        print("No audit entries")
        return {"entries": []}
    print(f"{'OP':25s} {'AGENT':15s} {'SUCCESS':>8} {'ERROR':25s} {'TIME':>10}")
    print("-" * 90)
    for e in logs:
        err = (e.get("error") or "")[:25]
        ts = time.strftime("%H:%M:%S", time.localtime(e["timestamp"]))
        print(f"{e['op']:25s} {e['agent_id']:15s} {str(e['success']):>8} {err:25s} {ts:>10}")
    return {"entries": logs}


def cmd_chain(args):
    if not args:
        print("Usage: chain <call_id>")
        return {"success": False, "error": "call_id required"}
    from l1.kernel.tool_chain import get_tool_chain
    chain = get_tool_chain()
    v = chain.verify(args[0])
    print(f"Chain verify: {'PASS' if v['valid'] else 'FAIL'} (depth {v['depth']})")
    for step in v["steps"]:
        print(f"  {step['depth']}: {step['tool']:25s} {step['call_id']:20s} {'✓' if step['fingerprint_match'] else '✗'}")
    return v


def cmd_interrupts(args):
    from l1.kernel.interrupt import get_table
    t = get_table()
    counts = t.counts()
    recent = t.recent(10)
    print("Interrupt counts:")
    for name, count in sorted(counts.items()):
        if count > 0:
            print(f"  {name:30s} {count}")
    if recent:
        print(f"\nRecent (last {len(recent)}):")
        for r in recent:
            print(f"  [{r['type']}] {r['agent']} — {r['reason'][:60]}")
    return {"counts": counts, "recent": recent}


def cmd_devices(args):
    from l1.kernel.device import get_device_manager
    dm = get_device_manager()
    devices = dm.list()
    if not devices:
        print("No devices registered")
        return {"devices": []}
    print(f"{'NAME':15s} {'TYPE':12s} {'HEALTH':10s} {'RATE':>6} {'CALLS':>6} {'ERRORS':>6}")
    print("-" * 60)
    for d in devices:
        print(f"{d['name']:15s} {d['type']:12s} {d['health']:10s} {d['rate_limit']:>6} {d['calls']:>6} {d['errors']:>6}")
    return {"devices": devices}


def cmd_shutdown(args):
    from l1.kernel.os import get_os
    r = get_os().shutdown()
    if r.get("success"):
        print(f"⏻ Shutdown OK: uptime={r.get('uptime', 0):.0f}s")
        for k, v in r.get("results", {}).items():
            print(f"  {k}: {v}")
    else:
        print(f"⏻ Shutdown FAILED: {r}")
    return r


def cmd_status(args):
    cmd_health(args)
    cmd_interrupts(args)
    cmd_ps(args)
    from l1.kernel import get_audit_log
    from l1.kernel.device import get_device_manager
    from l1.kernel.process import get_table
    from l3.agent_terminal import get_terminals
    try:
        from l4.ops_console import get_ops
        ops = get_ops()
        s = ops.summary()
        print(f"\nOps Console:")
        print(f"  Cells: {s.get('cell_count', 0)}")
        print(f"  Agents: {sum(len(c.get('agents', {})) for c in s.get('cells', {}).values())}")
        al = s.get('alerts', {})
        print(f"  Alerts: {al.get('total', 0)} (crit={al.get('crit', 0)}, warn={al.get('warn', 0)})")
    except Exception:
            pass
    from l1.kernel.params.kernel import SYSCALL_AUDIT_MAX
    print(f"\nSummary:")
    print(f"  Kernel: {cmd_health([])['status']}")
    print(f"  Processes: {len(get_table().list())}")
    print(f"  Terminals: {len(get_terminals())}")
    print(f"  Syscalls audited: {len(get_audit_log(limit=SYSCALL_AUDIT_MAX))}")
    print(f"  Devices: {len(get_device_manager().list())}")
    return {}


def cmd_sys(args):
    from l1.kernel.vfs import get_vfs
    path = args[0] if args else "/sys"
    r = get_vfs().read(path)
    if r.get("success"):
        print(r["content"])
    else:
        print(f"Error: {r.get('error','')}")
    return r


def cmd_dev(args):
    from l1.kernel.vfs import get_vfs
    path = args[0] if args else "/dev"
    r = get_vfs().read(path)
    if r.get("success"):
        print(r["content"])
    else:
        print(f"Error: {r.get('error','')}")
    return r


def cmd_setting(args):
    from l1.kernel.settings import get_settings
    s = get_settings()
    if not args:
        all_s = s.all()
        for k, v in sorted(all_s.items()):
            print(f"{k:35s} = {v}")
        return {"settings": all_s}
    if len(args) == 1:
        v = s.get(args[0])
        print(f"{args[0]} = {v}")
        return {args[0]: v}
    key = args[0]
    raw = " ".join(args[1:])
    try:
        val = int(raw)
    except ValueError:
        try:
            val = float(raw)
        except ValueError:
            val = raw
    r = s.set(key, val)
    print(f"Set: {key} = {val}")
    return r


def cmd_card_list(args):
    from l3.card_registry import get_registry
    cr = get_registry()
    cards = cr.list(state=None)
    if not cards:
        print("No cards")
        return {"cards": []}
    print(f"{'ID':20s} {'STATE':12s} {'PRI':>3} {'ELAPSED':>8} {'INTENT'}")
    print("-" * 80)
    for c in cards[:20]:
        print(f"{c['id']:20s} {c['state']:12s} {c['priority']:>3} {str(c.get('elapsed','')):>8}s {c['intent'][:40]}")
    return {"cards": cards}


def cmd_card_submit(args):
    if not args:
        print("Usage: card-submit <intent> [domain]")
        return {"success": False}
    from l3.card_registry import get_registry
    cr = get_registry()
    intent = " ".join(args)
    cid = cr.submit(intent, ".")
    print(f"Card submitted: {cid}")
    return {"success": True, "card_id": cid}


def cmd_card_cancel(args):
    if not args:
        print("Usage: card-cancel <card_id>")
        return {"success": False}
    from l3.card_registry import get_registry
    cr = get_registry()
    ok = cr.cancel(args[0])
    print(f"Cancelled: {ok}")
    return {"success": ok}


COMMANDS = {
    "boot": cmd_boot, "health": cmd_health, "ps": cmd_ps,
    "card": cmd_card, "card-list": cmd_card_list,
    "card-submit": cmd_card_submit, "card-cancel": cmd_card_cancel,
    "tools": cmd_tools, "audit": cmd_audit,
    "chain": cmd_chain, "interrupts": cmd_interrupts,
    "devices": cmd_devices, "status": cmd_status,
    "sys": cmd_sys, "dev": cmd_dev, "setting": cmd_setting,
    "shutdown": cmd_shutdown,
    "restart": lambda a: (lambda r: cmd_boot(a) or r)(cmd_shutdown(a)),
}
