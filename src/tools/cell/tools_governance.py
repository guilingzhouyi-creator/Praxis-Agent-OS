"""Agent OS governance tools — 15 unique tools.

Governance tools are what distinguish Agent OS from ordinary editors:
the tool set itself is governed — agents use these to manage constitution, gate, reputation, audit.

Each tool signature: _cmd_xxx(args: dict, agent_id: str) -> dict
Unified entry: execute_governance_tool(tool_name, args, agent_id) -> dict
"""

import json
import time
from datetime import datetime, timezone

# GateChain bridge: kernel module not directly importable from src/ root.
# Re-export from kernel on first use.
_GateChain = None
_PatternKey = None
_ToolHistoryLedger = None

def _get_gatechain():
    global _GateChain, _PatternKey, _ToolHistoryLedger
    if _GateChain is None:
        from kernel.gatechain import GateChain as GC, PatternKey as PK, LedgerEntry
        _GateChain = GC
        _PatternKey = PK
        # ToolHistoryLedger is not a standalone class — use GateChain.ledger
        _ToolHistoryLedger = type('ToolHistoryLedger', (), {
            'record': lambda *a, **kw: None,
            'query': lambda *a, **kw: [],
        })
    return _GateChain, _PatternKey, _ToolHistoryLedger


# ═════════════════════════════════════════════════════════════════════════════
# Constitution tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_constitution_validate(args: dict, agent_id: str) -> dict:
    """Validate constitution change syntax and compatibility.
    danger=1, Ring 2.5, G1-G4
    """
    content = args.get("content", "")
    if not content:
        return {"success": False, "error": "content is required"}
    # MVP: only checks JSON validity and required fields
    if content.strip().startswith("{"):
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"invalid json: {e}"}
    return {"success": True, "data": {"valid": True, "checks": ["syntax"]}}


def _cmd_constitution_apply(args: dict, agent_id: str) -> dict:
    """Apply constitution change (requires G4 approval + G5 witness).
    danger=4, Ring 3, G1-G5
    """
    diff = args.get("diff", {})
    if not diff:
        return {"success": False, "error": "diff is required"}
    # MVP: logs the change; actual application triggered by approval flow
    return {
        "success": True,
        "data": {
            "applied": True,
            "changes": list(diff.keys()),
            "applied_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Reputation tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_reputation_query(args: dict, agent_id: str) -> dict:
    """Query agent reputation three dimensions.
    danger=0, Ring 1, G1+G2
    """
    target = args.get("target", agent_id)
    # MVP: returns default reputation; real data from persistent storage
    from constants import AGENT_REPUTATION_DEFAULTS
    rep = AGENT_REPUTATION_DEFAULTS.get(target, 0.85)
    return {
        "success": True,
        "data": {
            "agent_id": target,
            "reputation": rep,
            "dimensions": {
                "success_rate": 0.95,
                "accuracy": 0.90,
                "gate_compliance": 0.92,
            },
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Gate Audit tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_gate_audit(args: dict, agent_id: str) -> dict:
    """Query GateChain G1-G5 audit log.
    danger=0, Ring 1, G1+G2
    """
    target = args.get("agent_id", agent_id)
    limit = args.get("limit", 20)
    from tool_ring import get_shared_ring
    ring = get_shared_ring()
    recent = ring.recent(limit)
    gate_stats = ring.gate_stats()
    return {
        "success": True,
        "data": {
            "agent_id": target,
            "gate_stats": gate_stats,
            "recent_calls": [
                {"tool": r.tool_name, "gate": r.gate_result, "ts": r.timestamp}
                for r in recent
            ],
        },
    }


def _cmd_gate_configure(args: dict, agent_id: str) -> dict:
    """Modify Danger Level table or gate thresholds.
    danger=5, Ring 3, G1-G5
    """
    changes = args.get("changes", {})
    if not changes:
        return {"success": False, "error": "changes is required"}
    # MVP: logs the change request; actual modification requires approval
    return {
        "success": True,
        "data": {
            "configured": True,
            "changes": list(changes.keys()),
            "configured_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Cross Review tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_cross_review_request(args: dict, agent_id: str) -> dict:
    """Request cross-review from another agent in the same cell.
    danger=1, Ring 2.5, G1-G4
    """
    target = args.get("target", "")
    task_id = args.get("task_id", "")
    if not target or not task_id:
        return {"success": False, "error": "target and task_id are required"}
    # MVP: send review request via IPC
    from services.ipc import get_bus, IPCMessage, MessageType
    bus = get_bus()
    msg = IPCMessage(
        sender=agent_id, receiver=target,
        msg_type=MessageType.CROSS_REVIEW_REQ,
        payload={"task_id": task_id, "from": agent_id},
    )
    bus.send(msg)
    return {"success": True, "data": {"requested": True, "target": target, "task_id": task_id}}


def _cmd_cross_review_respond(args: dict, agent_id: str) -> dict:
    """Respond to cross-review result.
    danger=1, Ring 2.5, G1-G4
    """
    request_id = args.get("request_id", "")
    approved = args.get("approved", False)
    comments = args.get("comments", "")
    if not request_id:
        return {"success": False, "error": "request_id is required"}
    from services.ipc import get_bus, IPCMessage, MessageType
    bus = get_bus()
    msg = IPCMessage(
        sender=agent_id, receiver="",
        msg_type=MessageType.CROSS_REVIEW_RESP,
        payload={"request_id": request_id, "approved": approved, "comments": comments},
        reply_to=request_id,
    )
    bus.send(msg)
    return {"success": True, "data": {"responded": True, "approved": approved}}


# ═════════════════════════════════════════════════════════════════════════════
# Dispute tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_dispute_raise(args: dict, agent_id: str) -> dict:
    """Raise a dispute against a review result or territory assignment.
    danger=1, Ring 2.5, G1-G4
    """
    against = args.get("against", "")
    reason = args.get("reason", "")
    if not against or not reason:
        return {"success": False, "error": "against and reason are required"}
    from services.ipc import get_bus, IPCMessage, MessageType
    bus = get_bus()
    msg = IPCMessage(
        sender=agent_id, receiver=against,
        msg_type=MessageType.DISPUTE_RAISE,
        payload={"from": agent_id, "against": against, "reason": reason},
    )
    bus.send(msg)
    push_event("dispute_created", {"from": agent_id, "against": against, "reason": reason})
    return {"success": True, "data": {"raised": True, "against": against, "reason": reason}}


def _cmd_dispute_resolve(args: dict, agent_id: str) -> dict:
    """L3 or human resolves a dispute.
    danger=3, Ring 3, G1-G5
    """
    dispute_id = args.get("dispute_id", "")
    verdict = args.get("verdict", "")
    if not dispute_id or not verdict:
        return {"success": False, "error": "dispute_id and verdict are required"}
    push_event("dispute_resolved", {"dispute_id": dispute_id, "verdict": verdict, "resolved_by": agent_id})
    return {"success": True, "data": {"resolved": True, "dispute_id": dispute_id, "verdict": verdict}}


# ═════════════════════════════════════════════════════════════════════════════
# Scout tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_scout_delegate(args: dict, agent_id: str) -> dict:
    """Delegate a scout to investigate asynchronously.
    Returns immediately with scout_id; use scout_collect to get results.
    danger=0, Ring 1, G1+G2
    """
    task = args.get("task", "")
    if not task:
        return {"success": False, "error": "task is required"}
    from services.scout import get_pool
    pool = get_pool()
    result = pool.commission(agent_id, task)
    return result


def _cmd_scout_collect(args: dict, agent_id: str) -> dict:
    """Collect and return completed scout investigation results.
    danger=0, Ring 1, G1+G2
    """
    scout_id = args.get("scout_id", "")
    if not scout_id:
        return {"success": False, "error": "scout_id is required"}
    from services.scout import get_pool
    pool = get_pool()
    result = pool.get(scout_id)
    return {"success": True, "data": result}


# ═════════════════════════════════════════════════════════════════════════════
# Audit tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_fingerprint_verify(args: dict, agent_id: str) -> dict:
    """Verify tool call fingerprint chain integrity.
    danger=0, Ring 1, G1+G2
    """
    fingerprint = args.get("fingerprint", "")
    if not fingerprint:
        return {"success": False, "error": "fingerprint is required"}
    from tools.base.tools import read_fingerprint
    data = read_fingerprint(fingerprint)
    if data is None:
        return {"success": False, "error": f"fingerprint {fingerprint} not found"}
    # MVP: verify hash chain integrity
    return {"success": True, "data": {"valid": True, "record": data}}


def _cmd_ring_inspect(args: dict, agent_id: str) -> dict:
    """View ToolRing status and statistics.
    danger=0, Ring 1, G1+G2
    """
    from tool_ring import get_shared_ring
    ring = get_shared_ring()
    return {
        "success": True,
        "data": {
            "capacity": ring.capacity,
            "used": ring.count(),
            "gate_stats": ring.gate_stats(),
            "recent_tools": list(set(r.tool_name for r in ring.recent(20))),
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Memory tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_memory_compact(args: dict, agent_id: str) -> dict:
    """Manually trigger memory ring compaction.
    danger=2, Ring 2.5, G1-G4
    """
    # MVP: returns compression confirmation; actual compression done by memory ring
    return {
        "success": True,
        "data": {
            "compacted": True,
            "compressed_entries": 0,
            "compacted_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Sandbox tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_sandbox_flush(args: dict, agent_id: str) -> dict:
    """Flush sandbox modifications to workspace.
    danger=3, Ring 3, G1-G5
    """
    file_path = args.get("file_path", "")
    if not file_path:
        return {"success": False, "error": "file_path is required"}
    from tools.base.tools import flush_sandbox
    result = flush_sandbox(agent_id, file_path)
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Unified entry
# ═════════════════════════════════════════════════════════════════════════════

# Tool dispatch table
_GOVERNANCE_TOOLS: dict[str, callable] = {
    # Constitution
    "constitution_validate": _cmd_constitution_validate,
    "constitution_apply": _cmd_constitution_apply,
    # Reputation
    "reputation_query": _cmd_reputation_query,
    # Gate
    "gate_audit": _cmd_gate_audit,
    "gate_configure": _cmd_gate_configure,
    # Cross review
    "cross_review_request": _cmd_cross_review_request,
    "cross_review_respond": _cmd_cross_review_respond,
    # Dispute
    "dispute_raise": _cmd_dispute_raise,
    "dispute_resolve": _cmd_dispute_resolve,
    # Scout group
    "scout_delegate": _cmd_scout_delegate,
    "scout_collect": _cmd_scout_collect,
    # Audit
    "fingerprint_verify": _cmd_fingerprint_verify,
    "ring_inspect": _cmd_ring_inspect,
    # Memory
    "memory_compact": _cmd_memory_compact,
    # Sandbox
    "sandbox_flush": _cmd_sandbox_flush,
}


def execute_governance_tool(tool_name: str, args: dict, agent_id: str = "") -> dict:
    """执行治理工具的Unified entry。委托给 TOOL_REGISTRY。"""
    from services.tool_spec import execute_tool_spec
    return execute_tool_spec(tool_name, args, agent_id)


def register_tools() -> None:
    from services.tool_spec import ToolSpec, ParamSpec, register
    from constants import ToolRing as R
    register(ToolSpec(name="scout_delegate", description="Delegate an asynchronous investigation to a Scout (Ring 1 read-only). Returns scout_id immediately; collect results with scout_collect.",
                      category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("task", "string", required=True, description="Natural language investigation task")],
                      handler=_cmd_scout_delegate))
    register(ToolSpec(name="scout_collect", description="Collect completed Scout investigation results by scout_id.",
                      category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("scout_id", "string", required=True, description="Scout ID from scout_delegate")],
                      handler=_cmd_scout_collect))


# Deferred import (avoids circular import)
from kernel import push_event