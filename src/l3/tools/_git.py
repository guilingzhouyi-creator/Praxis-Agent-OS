"""Git tool handlers."""

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.system import LOG_TRUNC_500, LOG_TRUNC_2000
from l1.kernel.platform import run_args


def _git(args_list: list[str], timeout: int | None = None) -> dict:
    if timeout is None:
        timeout = get_tool_config("git_timeout", 30)
    try:
        r = run_args(["git"] + args_list, timeout=timeout)
        return {"success": r.returncode == 0, "stdout": r.stdout.strip()[:LOG_TRUNC_2000], "stderr": r.stderr.strip()[:LOG_TRUNC_500]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def git_commit(args: dict, agent_id: str) -> dict:
    """Stage all changes and commit with the given message; returns git result dict."""
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    r1 = _git(["add", "-A"])
    if not r1["success"]:
        return r1
    return _git(["commit", "-m", message])


def git_push(args: dict, agent_id: str) -> dict:
    """Push the current branch to its remote; returns git result dict."""
    return _git(["push"])


def git_branch(args: dict, agent_id: str) -> dict:
    """Run branch actions (list/create/switch/delete); returns git result dict."""
    action = args.get("action", "")
    name = args.get("name", "")
    if action == "list":
        return _git(["branch"])
    if action == "create" and name:
        return _git(["branch", name])
    if action == "switch" and name:
        return _git(["checkout", name])
    if action == "delete" and name:
        return _git(["branch", "-d", name])
    return {"success": False, "error": "invalid action or missing name"}
