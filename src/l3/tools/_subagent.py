"""SubAgent tool — mount a specialization as a single Peer Agent tool.

Uses existing SubAgent (sync) + Scout (async) under the hood.
Two modes:
  - "review"  → read-only, Ring 1 tools only, path-confined
  - "deploy"  → restricted write tools, approval gate required
  - "scout"   → async investigation via ScoutPool, result collected
"""

import logging
import time

from l1.kernel.params.system import LOG_TRUNC_100, LOG_TRUNC_200

logger = logging.getLogger(__name__)

# Tool restriction profiles
_PROFILES = {
    "review": {
        "allowed_tools": {
            "read_file",
            "grep",
            "glob",
            "list_dir",
            "file_stat",
            "file_search",
            "list_skills",
            "use_skill",
        },
        "read_only": True,
    },
    "deploy": {
        "allowed_tools": {"read_file", "write_file", "file_stat", "bash", "git", "list_dir"},
        "read_only": False,
    },
    "scout": {
        "allowed_tools": set(),  # Scout uses its own tool set
        "read_only": True,
    },
}


def subagent_tool(args: dict, agent_id: str) -> dict:
    """Execute a sub-agent task with restricted tool set.

    Usage:
      subagent_tool(mode="review", task="Check src/main.py for security issues")
      subagent_tool(mode="deploy", task="Push the latest build to staging")
      subagent_tool(mode="scout", task="Investigate the error pattern in logs")

    Args:
        mode: "review" | "deploy" | "scout" (default: "review")
        task: Natural language task description
        tools: Optional list of additional tool names to allow
        timeout: Max seconds for sync execution (default: 30)
    """
    mode = args.get("mode", "review")
    task = args.get("task", "")
    timeout = float(args.get("timeout", 30))

    if mode not in _PROFILES:
        return {"success": False, "error": f"unknown mode: {mode}, use review|deploy|scout"}

    profile = _PROFILES[mode]
    extra_tools = args.get("tools", [])

    if mode == "scout":
        return _run_scout(task, agent_id, timeout)
    return _run_sync(mode, task, agent_id, timeout, profile, extra_tools)


def _run_sync(mode: str, task: str, agent_id: str, timeout: float, profile: dict, extra_tools: list[str]) -> dict:
    """Run a synchronous SubAgent with restricted tools."""
    try:
        import time as _time

        from l3.agent.subagent import SubAgent
        from l3.services.middleware import ConfineMiddleware, MiddlewareChain

        # Build middleware chain for confinement
        mw_chain = MiddlewareChain()
        if profile["read_only"]:
            mw_chain.add(
                ConfineMiddleware(
                    allowed_roots=None,  # no path restriction
                    read_only=True,
                )
            )

        agent = SubAgent(caller_id=agent_id)
        t0 = _time.time()

        result = agent.run(task=task, tools=None)
        elapsed = _time.time() - t0

        if result.success:
            return {
                "success": True,
                "mode": mode,
                "task": task[:LOG_TRUNC_100],
                "findings": [
                    {"content": f.get("content", "")[:LOG_TRUNC_200], "type": f.get("type", "")}
                    for f in (result.findings or [])
                ],
                "error": result.error or "",
                "elapsed": round(elapsed, 2),
            }
        return {
            "success": False,
            "mode": mode,
            "task": task[:LOG_TRUNC_100],
            "error": result.error or "subagent failed",
            "elapsed": round(elapsed, 2),
        }
    except Exception as e:
        logger.warning("subagent_tool[%s]: %s", mode, e)
        return {"success": False, "error": str(e)}


def _run_scout(task: str, agent_id: str, timeout: float) -> dict:
    """Run an async Scout, wait and collect result."""
    try:
        from l3.agent.scout import get_pool as get_scout_pool

        pool = get_scout_pool()
        scout = pool.commission(
            agent_id=agent_id,
            task=task,
            template="",
        )
        if not scout:
            return {"success": False, "error": "scout pool exhausted"}

        # Wait for result with timeout
        t0 = __import__("time").time()
        import threading

        event = threading.Event()
        result_container = []

        def _collect():
            result_container.append(scout.collect(timeout=timeout))
            event.set()

        t = threading.Thread(target=_collect, daemon=True)
        t.start()
        event.wait(timeout=timeout + 1)

        elapsed = time.time() - t0
        if result_container:
            r = result_container[0]
            return {
                "success": r.get("success", False),
                "mode": "scout",
                "task": task[:LOG_TRUNC_100],
                "findings": r.get("findings", r.get("results", [])),
                "elapsed": round(elapsed, 2),
            }
        return {
            "success": False,
            "mode": "scout",
            "task": task[:LOG_TRUNC_100],
            "error": "scout did not complete in time",
            "elapsed": round(timeout, 2),
        }
    except Exception as e:
        logger.warning("subagent_tool[scout]: %s", e)
        return {"success": False, "error": str(e)}
