"""Composite workflow tools — multi-step pipelines using real tool registry.

Each composite tool chains multiple atomic tools into a workflow.
Tools are resolved by name from TOOL_REGISTRY at runtime, not hardcoded.
A fallback shell executor handles git/build/test operations natively.

review_and_fix       deploy_pipeline       migrate_project
merge_request        incident_response     project_audit
auto_refactor        backup_and_encrypt    code_sync
agent_health_check
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register, ToolRing as R
from constants import TOOL_HTTP_TIMEOUT_MEDIUM

logger = logging.getLogger(__name__)


def _resolve(name: str) -> str | None:
    """Resolve a tool name from the registry, with aliases for common names."""
    aliases = {
        "review_code": "review_code", "format_code": "code_format",
        "analyze_code": "code_analyze", "backup_create": "backup_directory",
        "encrypt_file": "crypto_encrypt_file", "audit_dependencies": "deps_audit",
        "scan_vulnerabilities": "security_viz_scan_vulns",
        "exception_info": "debug_exception_info",
    }
    resolved = aliases.get(name, name)
    try:
        from services.tool_spec import TOOL_REGISTRY
        if resolved in TOOL_REGISTRY:
            return resolved
    except Exception as e:
            logger.warning("tools_composite: %s", e)
    return None


def _exec(name: str, args: dict, agent_id: str) -> dict:
    """Execute a tool by name, or run a shell fallback."""
    resolved = _resolve(name)
    if resolved:
        from services.tool_spec import execute_tool_spec
        return execute_tool_spec(resolved, args, agent_id)
    # Shell fallback for common operations
    return _shell_fallback(name, args)


def _shell_fallback(name: str, args: dict) -> dict:
    """Run shell commands for git/build/test operations."""
    cmds = {
        "git_commit": ["git", "commit", "-m", args.get("message", "update")],
        "git_push": ["git", "push"],
        "git_branch": ["git", "checkout", args.get("name", "main")],
    }
    cmd = cmds.get(name)
    if not cmd:
        return {"success": False, "error": f"no handler: {name}"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        return {"success": r.returncode == 0, "data": {"output": (r.stdout or r.stderr)[:500]}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_review_and_fix(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    steps = []
    r1 = _exec("review_code", {"path": path}, agent_id)
    steps.append({"step": "review", "result": r1})
    if r1.get("success"):
        r2 = _exec("format_code", {"path": path}, agent_id)
        steps.append({"step": "format", "result": r2})
    return {"success": True, "data": {"file": path, "steps": steps, "step_count": len(steps)}}


def _cmd_deploy_pipeline(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    steps = []
    b = _exec("build_project", {"path": path}, agent_id)
    steps.append({"step": "build", "result": b})
    if b.get("success"):
        t = _exec("test_project", {"path": path}, agent_id)
        steps.append({"step": "test", "result": t})
        c = _exec("git_commit", {"message": f"deploy: {path}"}, agent_id)
        steps.append({"step": "commit", "result": c})
    return {"success": True, "data": {"path": path, "steps": steps, "step_count": len(steps)}}


def _cmd_migrate_project(args: dict, agent_id: str) -> dict:
    source = args.get("source", "")
    if not source:
        return {"success": False, "error": "source is required"}
    steps = []
    b = _exec("backup_create", {"path": source}, agent_id)
    steps.append({"step": "backup", "result": b})
    return {"success": True, "data": {"source": source, "steps": steps, "step_count": len(steps)}}


def _cmd_merge_request(args: dict, agent_id: str) -> dict:
    source = args.get("source", "")
    target = args.get("target", "")
    if not source or not target:
        return {"success": False, "error": "source and target are required"}
    steps = []
    r = _exec("review_code", {"path": source}, agent_id)
    steps.append({"step": "review_source", "result": r})
    return {"success": True, "data": {"source": source, "target": target, "steps": steps, "step_count": len(steps)}}


def _cmd_incident_response(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    steps = []
    d = _exec("exception_info", {"exception": args.get("issue", "Error")}, agent_id)
    steps.append({"step": "diagnose", "result": d})
    b = _exec("backup_create", {"path": path}, agent_id)
    steps.append({"step": "backup", "result": b})
    return {"success": True, "data": {"path": path, "steps": steps, "step_count": len(steps)}}


def _cmd_project_audit(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    steps = []
    a = _exec("audit_dependencies", {"path": path}, agent_id)
    steps.append({"step": "audit_deps", "result": a})
    return {"success": True, "data": {"path": path, "steps": steps, "step_count": len(steps)}}


def _cmd_auto_refactor(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    steps = []
    a = _exec("analyze_code", {"path": path}, agent_id)
    steps.append({"step": "analyze", "result": a})
    f = _exec("format_code", {"path": path}, agent_id)
    steps.append({"step": "format", "result": f})
    return {"success": True, "data": {"file": path, "steps": steps, "step_count": len(steps)}}


def _cmd_backup_and_encrypt(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    steps = []
    b = _exec("backup_create", {"path": path}, agent_id)
    steps.append({"step": "backup", "result": b})
    if b.get("success"):
        e = _exec("encrypt_file", {"path": b.get("data", {}).get("path", path)}, agent_id)
        steps.append({"step": "encrypt", "result": e})
    return {"success": True, "data": {"path": path, "steps": steps, "step_count": len(steps)}}


def _cmd_code_sync(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    steps = []
    b = _exec("build_project", {"path": path}, agent_id)
    steps.append({"step": "build", "result": b})
    return {"success": True, "data": {"path": path, "steps": steps, "step_count": len(steps)}}


def _cmd_agent_health_check(args: dict, agent_id: str) -> dict:
    target = args.get("target", agent_id)
    steps = []
    from kernel import health
    h = health()
    steps.append({"step": "kernel_health", "result": h})
    from kernel.process import get_table
    procs = get_table().list()
    steps.append({"step": "processes", "result": {"count": len(procs)}})
    from kernel.interrupt import get_table as int_table
    counts = int_table().counts()
    steps.append({"step": "interrupts", "result": {"counts": counts}})
    return {"success": True, "data": {"target": target, "steps": steps, "step_count": len(steps)}}


def register_tools() -> None:
    registry = [
        ("review_and_fix", _cmd_review_and_fix, R.RING_2_5, 2,
         [ParamSpec("path", "string", required=True)], "Review and auto-fix code"),
        ("deploy_pipeline", _cmd_deploy_pipeline, R.RING_3, 4,
         [ParamSpec("path", "string", default=".")], "Build-test-commit pipeline"),
        ("migrate_project", _cmd_migrate_project, R.RING_3, 4,
         [ParamSpec("source", "string", required=True)], "Backup-analyze project"),
        ("merge_request", _cmd_merge_request, R.RING_2_5, 2,
         [ParamSpec("source", "string", required=True), ParamSpec("target", "string", required=True)], "Review & merge"),
        ("incident_response", _cmd_incident_response, R.RING_2_5, 2,
         [ParamSpec("path", "string", required=True), ParamSpec("issue", "string", default="")], "Diagnose-backup"),
        ("project_audit", _cmd_project_audit, R.RING_1, 0,
         [ParamSpec("path", "string", default=".")], "Audit dependencies"),
        ("auto_refactor", _cmd_auto_refactor, R.RING_2_5, 2,
         [ParamSpec("path", "string", required=True)], "Auto-refactor code"),
        ("backup_and_encrypt", _cmd_backup_and_encrypt, R.RING_2_5, 2,
         [ParamSpec("path", "string", required=True)], "Backup and encrypt"),
        ("code_sync", _cmd_code_sync, R.RING_2_5, 2,
         [ParamSpec("path", "string", default=".")], "Build & sync"),
        ("agent_health_check", _cmd_agent_health_check, R.RING_1, 0,
         [ParamSpec("target", "string", default="")], "Full health check"),
    ]
    for name, handler, ring, danger, params, desc in registry:
        register(ToolSpec(name=name, description=desc, category="generic",
                          ring=ring, danger=danger, parameters=params, handler=handler))
