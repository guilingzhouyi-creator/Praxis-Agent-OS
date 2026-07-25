"""Build and test tools - 5 kinds.

build_project, test_project, test_run, test_watch, coverage_run
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_BUILD_TIMEOUT


def _run_cmd(cmd: list[str], timeout: int = 120) -> dict:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"success": r.returncode == 0, "data": {"stdout": r.stdout[-4096:], "stderr": r.stderr[-2048:], "code": r.returncode}}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timeout after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": f"command not found: {cmd[0]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_build_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    tool = args.get("tool", "auto")
    cwd = Path(path).resolve()
    if tool == "auto":
        if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists() or (cwd / "setup.cfg").exists():
            tool = "python"
        elif (cwd / "Cargo.toml").exists():
            tool = "cargo"
        elif (cwd / "package.json").exists():
            tool = "npm"
        elif (cwd / "go.mod").exists():
            tool = "go"
        else:
            return {"success": False, "error": f"unknown build system in {path}"}
    cmds = {
        "python": [sys.executable, "-m", "build", str(cwd)],
        "cargo": ["cargo", "build", "--manifest-path", str(cwd / "Cargo.toml")],
        "npm": ["npm", "run", "build"],
        "go": ["go", "build", "./..."],
    }
    cmd = cmds.get(tool)
    if not cmd:
        return {"success": False, "error": f"unknown tool: {tool}"}
    return _run_cmd(cmd)


def _cmd_test_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    tool = args.get("tool", "auto")
    test_path = args.get("test_path", "")
    cwd = Path(path).resolve()
    if tool == "auto":
        if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
            tool = "pytest"
        elif (cwd / "Cargo.toml").exists():
            tool = "cargo"
        elif (cwd / "package.json").exists():
            tool = "npm"
        elif (cwd / "go.mod").exists():
            tool = "go"
        else:
            tool = "pytest"
    cmds = {
        "pytest": [sys.executable, "-m", "pytest", test_path or str(cwd), "-q", "--no-header"],
        "cargo": ["cargo", "test", "--manifest-path", str(cwd / "Cargo.toml")],
        "npm": ["npm", "test"],
        "go": ["go", "test", "./..."],
    }
    cmd = cmds.get(tool)
    if not cmd:
        return {"success": False, "error": f"unknown tool: {tool}"}
    return _run_cmd(cmd, timeout=TOOL_BUILD_TIMEOUT)


def _cmd_test_run(args: dict, agent_id: str) -> dict:
    test_path = args.get("test_path", "")
    if not test_path:
        return {"success": False, "error": "test_path is required"}
    return _run_cmd([sys.executable, "-m", "pytest", test_path, "-v", "--tb=short", "-q"], timeout=TOOL_BUILD_TIMEOUT)


def _cmd_test_watch(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    return {"success": True, "data": {"message": "test_watch: 使用 ptw (pytest-watch) 或 nodemon", "path": path}}


def _cmd_coverage_run(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    report = args.get("report", "term")
    result = _run_cmd([sys.executable, "-m", "pytest", path, "--cov", "--cov-report", report, "-q", "--no-header"], timeout=TOOL_BUILD_TIMEOUT)
    return result


def register_tools() -> None:
    register(ToolSpec(name="build_project", description="Build project (auto-detect Python/Cargo/npm/go)", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("tool", "string", default="auto")],
                      handler=_cmd_build_project))
    register(ToolSpec(name="test_project", description="Run project tests (auto-detect test framework)", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("tool", "string", default="auto"),
                                  ParamSpec("test_path", "string", default="")],
                      handler=_cmd_test_project))
    register(ToolSpec(name="test_run", description="Run specified test file", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("test_path", "string", required=True)],
                      handler=_cmd_test_run))
    register(ToolSpec(name="test_watch", description="Watch files and auto-rerun tests (placeholder)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")],
                      handler=_cmd_test_watch))
    register(ToolSpec(name="coverage_run", description="Run tests with coverage report", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("report", "string", default="term")],
                      handler=_cmd_coverage_run))