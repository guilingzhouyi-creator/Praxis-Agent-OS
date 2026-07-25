"""Package management tools - 5 kinds.

pip_install, npm_install, cargo_build, gem_install, brew_install
"""

import os
import subprocess
import sys
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_BUILD_TIMEOUT, TOOL_PIP_TIMEOUT


def _run(cmd: list[str], timeout: int = 120) -> dict:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"success": r.returncode == 0, "data": {"stdout": r.stdout[-2048:], "stderr": r.stderr[-1024:], "code": r.returncode}}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timeout after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": f"command not found: {cmd[0]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_pip_install(args: dict, agent_id: str) -> dict:
    package = args.get("package", "")
    if not package:
        return {"success": False, "error": "package is required"}
    return _run([sys.executable, "-m", "pip", "install", package])


def _cmd_npm_install(args: dict, agent_id: str) -> dict:
    package = args.get("package", "")
    path = args.get("path", ".")
    if package:
        return _run(["npm", "install", package], timeout=TOOL_PIP_TIMEOUT)
    return _run(["npm", "install"], timeout=TOOL_PIP_TIMEOUT)


def _cmd_cargo_build(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    release = args.get("release", False)
    cmd = ["cargo", "build"]
    if release:
        cmd.append("--release")
    if path != ".":
        cmd.extend(["--manifest-path", os.path.join(path, "Cargo.toml")])
    return _run(cmd, timeout=TOOL_BUILD_TIMEOUT)


def _cmd_gem_install(args: dict, agent_id: str) -> dict:
    package = args.get("package", "")
    if not package:
        return {"success": False, "error": "package is required"}
    return _run(["gem", "install", package])


def _cmd_brew_install(args: dict, agent_id: str) -> dict:
    package = args.get("package", "")
    if not package:
        return {"success": False, "error": "package is required"}
    return _run(["brew", "install", package])


def register_tools() -> None:
    register(ToolSpec(name="pip_install", description="Install Python package", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("package", "string", required=True)],
                      handler=_cmd_pip_install))
    register(ToolSpec(name="npm_install", description="Install npm package", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("package", "string", default=""), ParamSpec("path", "string", default=".")],
                      handler=_cmd_npm_install))
    register(ToolSpec(name="cargo_build", description="Build Rust project", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("release", "bool", default=False)],
                      handler=_cmd_cargo_build))
    register(ToolSpec(name="gem_install", description="Install Ruby gem", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("package", "string", required=True)],
                      handler=_cmd_gem_install))
    register(ToolSpec(name="brew_install", description="Install Homebrew package", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("package", "string", required=True)],
                      handler=_cmd_brew_install))