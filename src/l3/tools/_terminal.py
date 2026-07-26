"""Terminal handler."""

import subprocess


def run_in_terminal(args: dict, agent_id: str) -> dict:
    command = args.get("command", "")
    timeout = args.get("timeout", 30)
    if not command:
        return {"success": False, "error": "command is required"}
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"success": r.returncode == 0, "stdout": r.stdout[:5000], "stderr": r.stderr[:2000], "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}
