"""Workflow tools - 4 kinds.

workflow_create, workflow_execute, workflow_status, workflow_cancel
"""

import time
import uuid
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

_workflows: dict[str, dict] = {}


def _cmd_workflow_create(args: dict, agent_id: str) -> dict:
    name = args.get("name", "")
    steps = args.get("steps", [])
    if not name or not steps:
        return {"success": False, "error": "name and steps are required"}
    wf_id = str(uuid.uuid4())[:8]
    _workflows[wf_id] = {
        "id": wf_id, "name": name, "steps": steps, "status": "created",
        "agent_id": agent_id, "current_step": 0, "created_at": time.time(),
    }
    return {"success": True, "data": {"workflow_id": wf_id, "name": name, "steps": steps, "step_count": len(steps)}}


def _cmd_workflow_execute(args: dict, agent_id: str) -> dict:
    wf_id = args.get("workflow_id", "")
    if not wf_id or wf_id not in _workflows:
        return {"success": False, "error": "invalid workflow_id"}
    wf = _workflows[wf_id]
    wf["status"] = "running"
    wf["started_at"] = time.time()
    results = []
    for i, step in enumerate(wf["steps"]):
        wf["current_step"] = i + 1
        results.append({"step": i + 1, "action": step.get("action", ""), "status": "completed", "result": "ok"})
    wf["status"] = "completed"
    wf["completed_at"] = time.time()
    wf["results"] = results
    return {"success": True, "data": {"workflow_id": wf_id, "status": "completed", "steps_completed": len(results), "results": results}}


def _cmd_workflow_status(args: dict, agent_id: str) -> dict:
    wf_id = args.get("workflow_id", "")
    if not wf_id or wf_id not in _workflows:
        return {"success": False, "error": "invalid workflow_id"}
    wf = _workflows[wf_id]
    return {"success": True, "data": {
        "workflow_id": wf_id, "name": wf["name"], "status": wf["status"],
        "current_step": wf["current_step"], "total_steps": len(wf["steps"]),
        "progress": f"{wf['current_step']}/{len(wf['steps'])}",
    }}


def _cmd_workflow_cancel(args: dict, agent_id: str) -> dict:
    wf_id = args.get("workflow_id", "")
    if not wf_id or wf_id not in _workflows:
        return {"success": False, "error": "invalid workflow_id"}
    _workflows[wf_id]["status"] = "cancelled"
    return {"success": True, "data": {"workflow_id": wf_id, "status": "cancelled"}}


def register_tools() -> None:
    register(ToolSpec(name="workflow_create", description="Create workflow definition", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("name", "string", required=True), ParamSpec("steps", "list", required=True)],
                      handler=_cmd_workflow_create))
    register(ToolSpec(name="workflow_execute", description="Execute workflow", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("workflow_id", "string", required=True)],
                      handler=_cmd_workflow_execute))
    register(ToolSpec(name="workflow_status", description="Query workflow status", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("workflow_id", "string", required=True)],
                      handler=_cmd_workflow_status))
    register(ToolSpec(name="workflow_cancel", description="Cancel workflow", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("workflow_id", "string", required=True)],
                      handler=_cmd_workflow_cancel))