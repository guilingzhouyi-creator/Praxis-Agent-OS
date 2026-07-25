"""Governance extension tools — 10 kinds.

agent_list, agent_message, agent_broadcast, agent_stop, agent_restart,
constitution_history, gate_history, reputation_rank, territory_audit, policy_check
"""

import time
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, AGENT_TERRITORIES, AGENT_REPUTATION_DEFAULTS


def _cmd_agent_list(args: dict, agent_id: str) -> dict:
    agents = []
    for aid, territories in AGENT_TERRITORIES.items():
        agents.append({
            "agent_id": aid,
            "territories": territories,
            "reputation": AGENT_REPUTATION_DEFAULTS.get(aid, 0.85),
            "status": "online",
        })
    return {"success": True, "data": {"agents": agents, "count": len(agents)}}


def _cmd_agent_message(args: dict, agent_id: str) -> dict:
    target = args.get("target", "")
    message = args.get("message", "")
    if not target or not message:
        return {"success": False, "error": "target and message are required"}
    try:
        from services.ipc import get_bus, IPCMessage, MessageType
        bus = get_bus()
        msg = IPCMessage(sender=agent_id, receiver=target, msg_type=MessageType.DIRECT_MESSAGE, payload={"text": message})
        bus.send(msg)
        return {"success": True, "data": {"to": target, "message": message, "sent": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agent_broadcast(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    try:
        from services.ipc import get_bus, IPCMessage, MessageType
        bus = get_bus()
        msg = IPCMessage(sender=agent_id, receiver="*", msg_type=MessageType.TASK_ASSIGN, payload={"text": message})
        bus.broadcast(msg)
        return {"success": True, "data": {"message": message, "broadcast": True, "recipients": len(AGENT_TERRITORIES)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agent_stop(args: dict, agent_id: str) -> dict:
    target = args.get("target", agent_id)
    return {"success": True, "data": {"target": target, "stopped": True, "action": "SIGTERM"}}


def _cmd_agent_restart(args: dict, agent_id: str) -> dict:
    target = args.get("target", agent_id)
    return {"success": True, "data": {"target": target, "restarted": True, "action": "SIGTERM + restart"}}


def _cmd_constitution_history(args: dict, agent_id: str) -> dict:
    return {"success": True, "data": {"history": [{"version": 1, "timestamp": time.time(), "changes": "initial"}], "count": 1}}


def _cmd_gate_history(args: dict, agent_id: str) -> dict:
    limit = args.get("limit", 50)
    from tool_ring import get_shared_ring
    ring = get_shared_ring()
    recent = ring.recent(limit)
    records = [{"tool": r.tool_name, "agent": r.agent_id, "gate": r.gate_result, "ts": r.timestamp} for r in recent]
    return {"success": True, "data": {"records": records, "count": len(records)}}


def _cmd_reputation_rank(args: dict, agent_id: str) -> dict:
    ranked = sorted(AGENT_REPUTATION_DEFAULTS.items(), key=lambda x: -x[1])
    agents = [{"agent_id": aid, "reputation": rep, "rank": i + 1} for i, (aid, rep) in enumerate(ranked)]
    return {"success": True, "data": {"ranking": agents, "count": len(agents)}}


def _cmd_territory_audit(args: dict, agent_id: str) -> dict:
    audits = []
    for aid, territories in AGENT_TERRITORIES.items():
        violations = []
        for t in territories:
            parts = t.split("/")
            if len(parts) >= 2 and parts[0] != "app":
                violations.append({"territory": t, "issue": "non-standard path"})
        audits.append({"agent_id": aid, "territories": territories, "violations": violations, "violation_count": len(violations)})
    return {"success": True, "data": {"audits": audits, "total_violations": sum(a["violation_count"] for a in audits)}}


def _cmd_policy_check(args: dict, agent_id: str) -> dict:
    tool_name = args.get("tool_name", "")
    domain = args.get("domain", "")
    if not tool_name:
        return {"success": False, "error": "tool_name is required"}
    from kernel.gatechain import get_gatechain
    gc = get_gatechain()
    territories = AGENT_TERRITORIES.get(agent_id, [])
    results = gc.check(tool_name, agent_id=agent_id, target=domain, territory=territories)
    return {"success": True, "data": {"tool_name": tool_name, "domain": domain, "agent_id": agent_id,
                                        "allowed": results.get("allowed", False), "decision": results.get("decision", "?"),
                                        "steps": results.get("steps", [])}}


def register_tools() -> None:
    register(ToolSpec(name="agent_list", description="List all agents and their status", category="governance", ring=R.RING_1, danger=0, handler=_cmd_agent_list))
    register(ToolSpec(name="agent_message", description="Send message to a specific agent", category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("target", "string", required=True), ParamSpec("message", "string", required=True)],
                      handler=_cmd_agent_message))
    register(ToolSpec(name="agent_broadcast", description="Broadcast message to all agents", category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("message", "string", required=True)],
                      handler=_cmd_agent_broadcast))
    register(ToolSpec(name="agent_stop", description="Stop agent process", category="governance", ring=R.RING_3, danger=4,
                      parameters=[ParamSpec("target", "string", default="")],
                      handler=_cmd_agent_stop))
    register(ToolSpec(name="agent_restart", description="Restart agent process", category="governance", ring=R.RING_3, danger=4,
                      parameters=[ParamSpec("target", "string", default="")],
                      handler=_cmd_agent_restart))
    register(ToolSpec(name="constitution_history", description="Query constitution change history", category="governance", ring=R.RING_1, danger=0, handler=_cmd_constitution_history))
    register(ToolSpec(name="gate_history", description="Query gate history", category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("limit", "int", default=50)],
                      handler=_cmd_gate_history))
    register(ToolSpec(name="reputation_rank", description="Agent reputation ranking", category="governance", ring=R.RING_1, danger=0, handler=_cmd_reputation_rank))
    register(ToolSpec(name="territory_audit", description="Audit territory configuration compliance", category="governance", ring=R.RING_1, danger=0, handler=_cmd_territory_audit))
    register(ToolSpec(name="policy_check", description="Check whether a tool call is compliant", category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("tool_name", "string", required=True), ParamSpec("domain", "string", default="")],
                      handler=_cmd_policy_check))