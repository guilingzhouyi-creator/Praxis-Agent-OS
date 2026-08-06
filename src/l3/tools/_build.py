"""Build/test tool handlers."""

from l1.kernel.discovery import get_config, get_tool_config
from l1.kernel.params.system import LOG_TRUNC_2000
from l1.kernel.platform import run_args

_BUILD_TIMEOUT = get_tool_config("build_timeout", 300)


def _get_build_detectors() -> list[tuple[str, ...]]:
    """Get build detectors from discovery, fall back to params defaults."""
    cfg = get_config("build_detectors")
    if cfg:
        return [tuple(v["cmd"]) for v in cfg.values()]
    from l1.kernel.params.tool import BUILD_DETECTORS
    return BUILD_DETECTORS


def _get_test_detectors() -> list[tuple[str, ...]]:
    """Get test detectors from discovery, fall back to params defaults."""
    cfg = get_config("test_detectors")
    if cfg:
        return [tuple(v["cmd"]) for v in cfg.values()]
    from l1.kernel.params.tool import TEST_DETECTORS
    return TEST_DETECTORS


def build_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    for cmd in _get_build_detectors():
        try:
            r = run_args(list(cmd), cwd=path, timeout=_BUILD_TIMEOUT)
            if r.returncode == 0:
                return {"success": True, "command": " ".join(cmd), "stdout": r.stdout[:LOG_TRUNC_2000]}
        except Exception:
            continue
    return {"success": False, "error": "no supported build system found"}


def test_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    for cmd in _get_test_detectors():
        try:
            r = run_args(list(cmd), cwd=path, timeout=_BUILD_TIMEOUT)
            if r.returncode == 0:
                return {"success": True, "command": " ".join(cmd), "stdout": r.stdout[:LOG_TRUNC_2000]}
            # Framework ran but tests failed: parse failure detail so the
            # caller (agent or AutoTestGate) can act on exact failing tests.
            from l3.tool_system.auto_test import parse_pytest_failures
            output = f"{r.stdout}\n{r.stderr}"
            failures = parse_pytest_failures(output)
            return {"success": False, "command": " ".join(cmd),
                    "failures": failures,
                    "stdout": r.stdout[:LOG_TRUNC_2000],
                    "stderr": r.stderr[:LOG_TRUNC_2000]}
        except Exception:
            continue
    return {"success": False, "error": "no supported test framework found"}


def execute_shell(args: dict, agent_id: str) -> dict:
    """Run a command via terminal tool with structured error handling."""
    from ._terminal import run_in_terminal
    return run_in_terminal(args, agent_id)


def deploy(args: dict, agent_id: str) -> dict:
    """Deploy code to target environment."""
    return execute_shell({"command": f"deploy {args.get('target', '')}", "timeout": _BUILD_TIMEOUT}, agent_id)


def db_migrate(args: dict, agent_id: str) -> dict:
    """Run database migration scripts."""
    return execute_shell({"command": f"db_migrate {args.get('migration', '')}", "timeout": _BUILD_TIMEOUT}, agent_id)


def rollback(args: dict, agent_id: str) -> dict:
    """Roll back a deployed version."""
    return execute_shell({"command": f"rollback {args.get('version', '')}", "timeout": _BUILD_TIMEOUT}, agent_id)
