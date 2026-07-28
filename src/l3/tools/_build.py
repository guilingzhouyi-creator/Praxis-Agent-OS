"""Build/test tool handlers."""

import subprocess

from l1.kernel.params.system import LOG_TRUNC_2000
from l1.kernel.params.tool import TOOL_BUILD_TIMEOUT, BUILD_DETECTORS, TEST_DETECTORS


def build_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    for cmd in BUILD_DETECTORS:
        try:
            r = subprocess.run(list(cmd), cwd=path, capture_output=True, text=True, timeout=TOOL_BUILD_TIMEOUT)
            if r.returncode == 0:
                return {"success": True, "command": " ".join(cmd), "stdout": r.stdout[:LOG_TRUNC_2000]}
        except Exception:
            continue
    return {"success": False, "error": "no supported build system found"}


def test_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    for cmd in TEST_DETECTORS:
        try:
            r = subprocess.run(list(cmd), cwd=path, capture_output=True, text=True, timeout=TOOL_BUILD_TIMEOUT)
            if r.returncode == 0:
                return {"success": True, "command": " ".join(cmd), "stdout": r.stdout[:LOG_TRUNC_2000]}
        except Exception:
            continue
    return {"success": False, "error": "no supported test framework found"}


def execute_shell(args: dict, agent_id: str) -> dict:
    """Run a command via terminal tool with structured error handling."""
    from ._terminal import run_in_terminal
    return run_in_terminal(args, agent_id)


def deploy(args: dict, agent_id: str) -> dict:
    """Deploy code to target environment."""
    return execute_shell({"command": f"deploy {args.get('target', '')}", "timeout": 300}, agent_id)


def db_migrate(args: dict, agent_id: str) -> dict:
    """Run database migration scripts."""
    return execute_shell({"command": f"db_migrate {args.get('migration', '')}", "timeout": 300}, agent_id)


def rollback(args: dict, agent_id: str) -> dict:
    """Roll back a deployed version."""
    return execute_shell({"command": f"rollback {args.get('version', '')}", "timeout": 300}, agent_id)
