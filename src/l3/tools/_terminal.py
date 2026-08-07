"""Terminal handler — cross-platform subprocess execution."""

import subprocess

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.system import LOG_TRUNC_2000, LOG_TRUNC_5000
from l1.kernel.platform import run_shell


def run_in_terminal(args: dict, agent_id: str) -> dict:
    """Run a shell command with a timeout; returns output dict."""
    command = args.get("command", "")
    timeout = args.get("timeout", get_tool_config("terminal_timeout", 30))
    if not command:
        return {"success": False, "error": "command is required"}
    try:
        proc = run_shell(command, timeout=timeout)
        return {"success": proc.returncode == 0, "stdout": proc.stdout[:LOG_TRUNC_5000] if proc.stdout else "",
                "stderr": proc.stderr[:LOG_TRUNC_2000] if proc.stderr else "", "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_shell(args: dict, agent_id: str) -> dict:
    """RING_3 tool: execute system command with witness approval."""
    return run_in_terminal(args, agent_id)
