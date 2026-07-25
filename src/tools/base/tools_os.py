"""Agent OS system tools — 12 OS-level capabilities.

Completes the Agent OS syscall layer:
process/heartbeat, resource monitor, lock sync, checkpoint, audit, territory, search.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM
from tool_ring import get_shared_ring
from kernel import push_event
from kernel.platform import grep_cmd
from .tools_os_lock import cmd_lock_acquire, cmd_lock_release, cmd_lock_status
from .tools_os_checkpoint import cmd_checkpoint_create, cmd_checkpoint_list

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# Heartbeat & Status
# ═════════════════════════════════════════════════════════════════════════════

_heartbeats: dict[str, float] = {}  # agent_id → last_heartbeat_ts
_heartbeat_lock = threading.Lock()


def _cmd_agent_heartbeat(args: dict, agent_id: str) -> dict:
    """Send heartbeat and query all agent liveness."""
    now = time.time()
    with _heartbeat_lock:
        _heartbeats[agent_id] = now
        alive = {}
        for aid, ts in list(_heartbeats.items()):
            alive[aid] = {"alive": now - ts < 30, "last_seen": ts}
    return {
        "success": True,
        "data": {
            "agent_id": agent_id,
            "timestamp": now,
            "heartbeat_interval": 5,
            "all_agents": alive,
        },
    }


def _cmd_agent_status(args: dict, agent_id: str) -> dict:
    """Query agent runtime status."""
    now = time.time()
    with _heartbeat_lock:
        last_hb = _heartbeats.get(agent_id, 0)
        alive = now - last_hb < 30
    from services.statecharts import AgentStatecharts
    sc = AgentStatecharts(agent_id)
    return {
        "success": True,
        "data": {
            "agent_id": agent_id,
            "alive": alive,
            "last_heartbeat": last_hb,
            "statecharts": sc.snapshot,
            "state": "running" if alive else "unknown",
            "uptime": now - last_hb if last_hb else 0,
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Resource Monitor
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_resource_usage(args: dict, agent_id: str) -> dict:
    """Query agent resource consumption."""
    from tool_ring import get_shared_ring
    ring = get_shared_ring()
    return {
        "success": True,
        "data": {
            "agent_id": agent_id,
            "token": {
                "budget": 73000,
                "consumed": ring.count() * 500,
                "remaining": 73000 - ring.count() * 500,
                "compression_ratio": 0.022,
            },
            "ring": {
                "capacity": ring.capacity,
                "used": ring.count(),
                "usage_pct": round(ring.count() / ring.capacity * 100, 1),
                "gate_stats": ring.gate_stats(),
            },
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# File Lock (process sync) — delegated to tools_os_lock.py
# ═════════════════════════════════════════════════════════════════════════════


def _cmd_lock_acquire(args: dict, agent_id: str) -> dict:
    return cmd_lock_acquire(args.get("path", ""), agent_id, args.get("ttl", 0))


def _cmd_lock_release(args: dict, agent_id: str) -> dict:
    return cmd_lock_release(args.get("path", ""), agent_id)


def _cmd_lock_status(args: dict, agent_id: str) -> dict:
    return cmd_lock_status()


# ═════════════════════════════════════════════════════════════════════════════
# Checkpoint — delegated to tools_os_checkpoint.py
# ═════════════════════════════════════════════════════════════════════════════


def _cmd_checkpoint_create(args: dict, agent_id: str) -> dict:
    return cmd_checkpoint_create(args.get("label", ""), agent_id, args.get("task_id", ""))


def _cmd_checkpoint_list(args: dict, agent_id: str) -> dict:
    return cmd_checkpoint_list(agent_id)


# ═════════════════════════════════════════════════════════════════════════════
# Constitution diff
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_constitution_diff(args: dict, agent_id: str) -> dict:
    """Diff old vs new constitution."""
    old = args.get("old", "")
    new = args.get("new", "")
    if not old or not new:
        return {"success": False, "error": "old and new content are required"}
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    added = [l for l in new_lines if l not in old_lines]
    removed = [l for l in old_lines if l not in new_lines]
    return {
        "success": True,
        "data": {
            "added": added[:20],
            "removed": removed[:20],
            "added_count": len(added),
            "removed_count": len(removed),
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Gate simulation
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_gate_dry_run(args: dict, agent_id: str) -> dict:
    """Simulate gate check without actually executing."""
    tool_name = args.get("tool_name", "")
    domain = args.get("domain", "")
    if not tool_name:
        return {"success": False, "error": "tool_name is required"}
    from kernel.gatechain import get_gatechain
    from constants import AGENT_TERRITORIES
    gc = get_gatechain()
    territories = AGENT_TERRITORIES.get(agent_id, [])
    results = gc.check(tool_name, agent_id=agent_id, target=domain, territory=territories)
    return {
        "success": True,
        "data": {
            "tool_name": tool_name,
            "agent_id": agent_id,
            "domain": domain,
            "all_pass": results.get("allowed", False),
            "decision": results.get("decision", "?"),
            "steps": results.get("steps", []),
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Audit export
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_audit_export(args: dict, agent_id: str) -> dict:
    """Export audit log."""
    limit = args.get("limit", 100)
    fmt = args.get("format", "json")
    from tool_ring import get_shared_ring
    ring = get_shared_ring()
    records = ring.recent(limit)
    data = [
        {"tool": r.tool_name, "agent": r.agent_id, "gate": r.gate_result,
         "success": r.success, "ts": r.timestamp, "fp": r.fingerprint}
        for r in records
    ]
    if fmt == "csv":
        import csv
        from io import StringIO
        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(["tool", "agent", "gate", "success", "timestamp", "fingerprint"])
        for d in data:
            w.writerow([d["tool"], d["agent"], d["gate"], d["success"], d["ts"], d["fp"]])
        return {"success": True, "data": {"csv": buf.getvalue(), "count": len(data)}}
    return {"success": True, "data": {"records": data, "count": len(data)}}


# ═════════════════════════════════════════════════════════════════════════════
# Territory query
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_territory_query(args: dict, agent_id: str) -> dict:
    """Query territory boundaries and overlaps."""
    target = args.get("agent_id", agent_id)
    from constants import AGENT_TERRITORIES
    territories = AGENT_TERRITORIES.get(target, [])
    all_territories = AGENT_TERRITORIES
    overlaps = {}
    for other, other_territories in all_territories.items():
        if other == target:
            continue
        common = [t for t in territories if t in other_territories]
        if common:
            overlaps[other] = common
    return {
        "success": True,
        "data": {
            "agent_id": target,
            "territories": territories,
            "count": len(territories),
            "overlaps": overlaps,
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Reputation history
# ═════════════════════════════════════════════════════════════════════════════

_reputation_history: dict[str, list[dict]] = defaultdict(list)


def _cmd_reputation_history(args: dict, agent_id: str) -> dict:
    """Query reputation history trend."""
    target = args.get("target", agent_id)
    limit = args.get("limit", 20)
    with _heartbeat_lock:
        history = list(_reputation_history.get(target, []))[-limit:]
    if not history:
        from constants import AGENT_REPUTATION_DEFAULTS
        rep = AGENT_REPUTATION_DEFAULTS.get(target, 0.85)
        history = [
            {"ts": time.time() - i * 3600, "reputation": round(rep - i * 0.01, 3)}
            for i in range(5)
        ]
    return {
        "success": True,
        "data": {
            "agent_id": target,
            "history": history,
            "trend": "up" if len(history) >= 2 and history[-1]["reputation"] > history[0]["reputation"] else "down",
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# File search
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_file_search(args: dict, agent_id: str) -> dict:
    """Full-text search file content (regex supported)."""
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    max_results = args.get("max_results", 50)
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    try:
        import subprocess
        cmd = grep_cmd(pattern, path, max_count=max_results)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:max_results]
        return {"success": True, "data": {"results": lines, "count": len(lines), "pattern": pattern}}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Skill tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_skill_list(args: dict, agent_id: str) -> dict:
    try:
        from kernel.skill import get_skill_manager
        sm = get_skill_manager()
        skills = sm.list()
        return {"success": True, "data": {"skills": skills, "count": len(skills)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_skill_view(args: dict, agent_id: str) -> dict:
    name = args.get("name", "")
    if not name:
        return {"success": False, "error": "name is required"}
    try:
        from kernel.skill import get_skill_manager
        sm = get_skill_manager()
        skill = sm.get(name)
        if not skill:
            return {"success": False, "error": f"skill not found: {name}"}
        return {"success": True, "data": {"name": name, "content": skill}}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Tool registration
# ═════════════════════════════════════════════════════════════════════════════

def register_tools() -> None:
    register(ToolSpec(name="agent_heartbeat", description="Send heartbeat and query agent liveness",
                      category="os", ring=R.RING_1, danger=0, handler=_cmd_agent_heartbeat))
    register(ToolSpec(name="agent_status", description="Query agent runtime status (Statecharts + liveness)",
                      category="os", ring=R.RING_1, danger=0, handler=_cmd_agent_status,
                      parameters=[ParamSpec("agent_id", "string", default="", description="Target agent")]))
    register(ToolSpec(name="resource_usage", description="Query agent resource consumption (Token/Ring/Gate)",
                      category="os", ring=R.RING_1, danger=0, handler=_cmd_resource_usage))
    register(ToolSpec(name="lock_acquire", description="Acquire file lock (mutual-exclusion write, prevent concurrent overwrite)",
                      category="os", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True, description="File path"),
                                  ParamSpec("ttl", "int", default=300, description="Lock timeout in seconds")],
                      handler=_cmd_lock_acquire))
    register(ToolSpec(name="lock_release", description="Release file lock",
                      category="os", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True, description="File path")],
                      handler=_cmd_lock_release))
    register(ToolSpec(name="lock_status", description="Query all file lock statuses",
                      category="os", ring=R.RING_1, danger=0, handler=_cmd_lock_status))
    register(ToolSpec(name="checkpoint_create", description="Create checkpoint (requires G4 approval + G5 witness)",
                      category="os", ring=R.RING_3, danger=4,
                      parameters=[ParamSpec("label", "string", default="", description="Checkpoint label"),
                                  ParamSpec("task_id", "string", default="", description="Associated task ID")],
                      handler=_cmd_checkpoint_create))
    register(ToolSpec(name="checkpoint_list", description="List checkpoints",
                      category="os", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("agent_id", "string", default="", description="Target agent")],
                      handler=_cmd_checkpoint_list))
    register(ToolSpec(name="constitution_diff", description="Diff old vs new constitution",
                      category="governance", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("old", "string", required=True, description="Old constitution content"),
                                  ParamSpec("new", "string", required=True, description="New constitution content")],
                      handler=_cmd_constitution_diff))
    register(ToolSpec(name="gate_dry_run", description="Simulate gate check without actually executing",
                      category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("tool_name", "string", required=True, description="Tool name"),
                                  ParamSpec("domain", "string", default="", description="Target domain")],
                      handler=_cmd_gate_dry_run))
    register(ToolSpec(name="audit_export", description="Export audit log (JSON/CSV)",
                      category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("limit", "int", default=100, description="Max entries"),
                                  ParamSpec("format", "string", default="json", description="json/csv")],
                      handler=_cmd_audit_export))
    register(ToolSpec(name="territory_query", description="Query territory boundaries and overlaps",
                      category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("agent_id", "string", default="", description="Target agent")],
                      handler=_cmd_territory_query))
    register(ToolSpec(name="reputation_history", description="Query reputation history trend",
                      category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("target", "string", default="", description="Target agent"),
                                  ParamSpec("limit", "int", default=20, description="Number of entries")],
                      handler=_cmd_reputation_history))
    register(ToolSpec(name="file_search", description="Full-text search file content (regex supported)",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("pattern", "string", required=True, description="Search pattern"),
                                  ParamSpec("path", "string", default=".", description="Search path"),
                                  ParamSpec("max_results", "int", default=50, description="Max results")],
                      handler=_cmd_file_search))
    register(ToolSpec(name="skill_list", description="List all installed skills",
                      category="os", ring=R.RING_1, danger=0,
                      handler=_cmd_skill_list))
    register(ToolSpec(name="skill_view", description="View a skill's full content",
                      category="os", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("name", "string", required=True, description="Skill name")],
                      handler=_cmd_skill_view))
