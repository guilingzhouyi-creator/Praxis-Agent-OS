"""Docker tools - 5 kinds.

docker_build, docker_run, docker_compose, container_list, image_list
"""

import json
import subprocess
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_BUILD_TIMEOUT


def _docker(cmd: list[str], timeout: int = 120) -> dict:
    try:
        r = subprocess.run(["docker"] + cmd, capture_output=True, text=True, timeout=timeout)
        return {"success": r.returncode == 0, "data": {"stdout": r.stdout[-4096:], "stderr": r.stderr[-2048:], "code": r.returncode}}
    except FileNotFoundError:
        return {"success": False, "error": "docker not found"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_docker_build(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    tag = args.get("tag", "")
    cmd = ["build", path]
    if tag:
        cmd.extend(["-t", tag])
    return _docker(cmd, timeout=TOOL_BUILD_TIMEOUT)


def _cmd_docker_run(args: dict, agent_id: str) -> dict:
    image = args.get("image", "")
    command = args.get("command", "")
    ports = args.get("ports", [])
    if not image:
        return {"success": False, "error": "image is required"}
    cmd = ["run", "--rm"]
    for p in ports:
        cmd.extend(["-p", str(p)])
    cmd.append(image)
    if command:
        cmd.append(command)
    return _docker(cmd, timeout=TOOL_BUILD_TIMEOUT)


def _cmd_docker_compose(args: dict, agent_id: str) -> dict:
    action = args.get("action", "up")
    path = args.get("path", ".")
    file = args.get("file", "docker-compose.yml")
    cmd = ["compose", "-f", file, action]
    if action == "up":
        cmd.append("-d")
    return _docker(cmd, timeout=TOOL_BUILD_TIMEOUT)


def _cmd_container_list(args: dict, agent_id: str) -> dict:
    all_containers = args.get("all", False)
    cmd = ["ps", "-a"] if all_containers else ["ps"]
    r = _docker(cmd)
    if r["success"]:
        lines = r["data"]["stdout"].splitlines()
        containers = []
        for line in lines[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 7:
                containers.append({"id": parts[0], "image": parts[1], "status": parts[4], "name": parts[-1]})
        r["data"]["containers"] = containers
        r["data"]["count"] = len(containers)
    return r


def _cmd_image_list(args: dict, agent_id: str) -> dict:
    r = _docker(["images"])
    if r["success"]:
        lines = r["data"]["stdout"].splitlines()
        images = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 5:
                images.append({"repository": parts[0], "tag": parts[1], "id": parts[2], "size": parts[4]})
        r["data"]["images"] = images
        r["data"]["count"] = len(images)
    return r


def register_tools() -> None:
    register(ToolSpec(name="docker_build", description="Build Docker image", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("tag", "string", default="")],
                      handler=_cmd_docker_build))
    register(ToolSpec(name="docker_run", description="Run Docker container", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("image", "string", required=True), ParamSpec("command", "string", default=""),
                                  ParamSpec("ports", "list", default=[])],
                      handler=_cmd_docker_run))
    register(ToolSpec(name="docker_compose", description="Execute Docker Compose operation", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("action", "string", default="up"), ParamSpec("path", "string", default="."),
                                  ParamSpec("file", "string", default="docker-compose.yml")],
                      handler=_cmd_docker_compose))
    register(ToolSpec(name="container_list", description="List Docker containers", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("all", "bool", default=False)],
                      handler=_cmd_container_list))
    register(ToolSpec(name="image_list", description="List Docker images", category="generic",
                      ring=R.RING_1, danger=0,
                      handler=_cmd_image_list))