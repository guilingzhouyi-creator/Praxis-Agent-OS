"""Terminal handler — cross-platform subprocess execution."""

import subprocess

from l1.kernel.platform import IS_WINDOWS, run_shell


def run_in_terminal(args: dict, agent_id: str) -> dict:
    command = args.get("command", "")
    timeout = args.get("timeout", 30)
    if not command:
        return {"success": False, "error": "command is required"}
    try:
        proc = run_shell(command, timeout=timeout)
        return {"success": proc.returncode == 0, "stdout": proc.stdout[:5000] if proc.stdout else "",
                "stderr": proc.stderr[:2000] if proc.stderr else "", "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_shell(args: dict, agent_id: str) -> dict:
    """RING_3 tool: execute system command with witness approval."""
    return run_in_terminal(args, agent_id)
