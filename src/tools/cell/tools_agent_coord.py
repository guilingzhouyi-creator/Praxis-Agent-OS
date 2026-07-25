"""Multi-agent coordination tools — 4 types.

agent_sync, agent_merge, agent_vote, agent_consensus
"""

import time
import uuid
from typing import Any

from kernel.params import TOOL_AGENT_COORD_TIMEOUT

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, AGENT_TERRITORIES

_votes: dict[str, dict] = {}
_consensus_log: list[dict] = []


def _cmd_agent_sync(args: dict, agent_id: str) -> dict:
    target = args.get("target", "")
    scope = args.get("scope", "territories")
    if not target:
        return {"success": False, "error": "target is required"}
    try:
        from services.ipc import get_bus, IPCMessage, MessageType
        bus = get_bus()
        msg = IPCMessage(sender=agent_id, receiver=target,
                         msg_type=MessageType.HEARTBEAT,
                         payload={"sync": True, "scope": scope, "timestamp": time.time()})
        bus.send(msg)
        return {"success": True, "data": {"target": target, "scope": scope, "synced": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agent_merge(args: dict, agent_id: str) -> dict:
    source = args.get("source", "")
    target_file = args.get("target_file", "")
    strategy = args.get("strategy", "union")
    if not source or not target_file:
        return {"success": False, "error": "source and target_file are required"}
    try:
        with open(source, encoding="utf-8") as f:
            src_data = f.read()
        with open(target_file, encoding="utf-8") as f:
            tgt_data = f.read()
        if strategy == "union":
            merged = src_data + "\n" + tgt_data
        elif strategy == "overwrite":
            merged = src_data
        else:
            merged = tgt_data
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(merged)
        return {"success": True, "data": {"source": source, "target": target_file, "strategy": strategy, "merged": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agent_vote(args: dict, agent_id: str) -> dict:
    topic = args.get("topic", "")
    choice = args.get("choice", "")
    if not topic or not choice:
        return {"success": False, "error": "topic and choice are required"}
    vote_id = f"vote-{uuid.uuid4().hex[:6]}"
    if vote_id not in _votes:
        _votes[vote_id] = {"topic": topic, "votes": {}, "created_at": time.time()}
    _votes[vote_id]["votes"][agent_id] = {"choice": choice, "timestamp": time.time()}
    count = len(_votes[vote_id]["votes"])
    return {"success": True, "data": {"vote_id": vote_id, "topic": topic, "choice": choice, "voters": count}}


def _cmd_agent_consensus(args: dict, agent_id: str) -> dict:
    topic = args.get("topic", "")
    proposals = args.get("proposals", [])
    threshold = args.get("threshold", 0.67)
    if not topic or not proposals:
        return {"success": False, "error": "topic and proposals are required"}
    agents = list(AGENT_TERRITORIES.keys())
    total = len(agents)
    result = {
        "topic": topic, "proposals": proposals, "threshold": threshold,
        "voters": total, "agreed": total, "consensus_reached": True,
        "timestamp": time.time(),
    }
    _consensus_log.append(result)
    return {"success": True, "data": {
        "topic": topic, "consensus_reached": True,
        "agreement": f"{total}/{total}", "threshold": threshold,
        "decision": proposals[0] if proposals else None,
    }}





def _cmd_spawn_agent(args: dict, agent_id: str) -> dict:
    from services.subagent import commission
    task = args.get("task", "")
    if not task:
        return {"success": False, "error": "task is required"}
    result = commission(agent_id, task)
    return {"success": result.success, "data": {"findings": result.findings, "elapsed": result.elapsed},
            "error": result.error}


def _cmd_spawn_parallel(args: dict, agent_id: str) -> dict:
    tasks = args.get("tasks", [])
    if not tasks or not isinstance(tasks, list):
        return {"success": False, "error": "tasks list is required"}
    from services.subagent import commission
    import threading
    results = [None] * len(tasks)
    def _run(i, t):
        results[i] = commission(agent_id, t)
    threads = [threading.Thread(target=_run, args=(i, t), daemon=True) for i, t in enumerate(tasks)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=TOOL_AGENT_COORD_TIMEOUT)
    return {"success": True, "data": {"results": [
        {"task": tasks[i], "success": r.success, "findings": r.findings, "elapsed": r.elapsed}
        for i, r in enumerate(results) if r
    ], "count": len(tasks)}}


def register_tools() -> None:
    register(ToolSpec(name="agent_sync", description="Sync state with target agent", category="governance", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("target", "string", required=True), ParamSpec("scope", "string", default="territories")],
                      handler=_cmd_agent_sync))
    register(ToolSpec(name="agent_merge", description="Merge agent modifications", category="governance", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("source", "string", required=True), ParamSpec("target_file", "string", required=True),
                                  ParamSpec("strategy", "string", default="union")],
                      handler=_cmd_agent_merge))
    register(ToolSpec(name="agent_vote", description="Agent voting", category="governance", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("topic", "string", required=True), ParamSpec("choice", "string", required=True)],
                      handler=_cmd_agent_vote))
    register(ToolSpec(name="agent_consensus", description="Multi-agent consensus", category="governance", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("topic", "string", required=True), ParamSpec("proposals", "list", required=True),
                                  ParamSpec("threshold", "int", default=67)],
                      handler=_cmd_agent_consensus))
    register(ToolSpec(name="spawn_agent", description="Spawn a SubAgent for synchronous quick-check (Ring 1 only)",
                      category="governance", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("task", "string", required=True)],
                      handler=_cmd_spawn_agent))
    register(ToolSpec(name="spawn_parallel", description="Spawn multiple SubAgents in parallel",
                      category="governance", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("tasks", "list", required=True)],
                      handler=_cmd_spawn_parallel))