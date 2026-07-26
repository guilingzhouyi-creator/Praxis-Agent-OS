"""Build/test tool handlers."""

import subprocess

from kernel.params import TOOL_BUILD_TIMEOUT


def build_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    cmds = [("python", "-m", "build"), ("cargo", "build"), ("npm", "run", "build")]
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=TOOL_BUILD_TIMEOUT)
            if r.returncode == 0:
                return {"success": True, "command": " ".join(cmd), "stdout": r.stdout[:2000]}
        except Exception:
            continue
    return {"success": False, "error": "no supported build system found"}


def test_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    cmds = [("python", "-m", "pytest"), ("cargo", "test"), ("npm", "test")]
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=TOOL_BUILD_TIMEOUT)
            if r.returncode == 0:
                return {"success": True, "command": " ".join(cmd), "stdout": r.stdout[:2000]}
        except Exception:
            continue
    return {"success": False, "error": "no supported test framework found"}
