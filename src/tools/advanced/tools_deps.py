"""Dependency management tools - 5 kinds.

dependency_list, dependency_graph, dependency_update, install_package, check_version
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM, TOOL_PIP_TIMEOUT


def _parse_pyproject_deps(path: Path) -> list[dict]:
    deps = []
    try:
        import tomllib
        with open(path / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        for key in ["dependencies", "optional-dependencies"]:
            section = data.get("project", {}).get(key, {})
            if isinstance(section, list):
                for dep in section:
                    deps.append({"name": dep.split(">=")[0].split("==")[0].strip(), "spec": dep, "source": "pyproject.toml"})
            elif isinstance(section, dict):
                for group, items in section.items():
                    for item in items:
                        deps.append({"name": item.split(">=")[0].split("==")[0].strip(), "spec": item, "group": group, "source": "pyproject.toml"})
    except Exception as e:
            logger.warning("tools_deps: %s", e)
    return deps


def _parse_requirements(path: Path) -> list[dict]:
    deps = []
    req_file = path / "requirements.txt"
    if req_file.exists():
        try:
            with open(req_file, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        deps.append({"name": line.split(">=")[0].split("==")[0].strip(), "spec": line, "source": "requirements.txt"})
        except Exception as e:
            logger.warning("tools_deps: %s", e)
    return deps


def _parse_package_json(path: Path) -> list[dict]:
    deps = []
    pkg_file = path / "package.json"
    if pkg_file.exists():
        try:
            with open(pkg_file) as f:
                data = json.load(f)
            for key, items in [("dependencies", "dependencies"), ("devDependencies", "devDependencies")]:
                for name, ver in data.get(key, {}).items():
                    deps.append({"name": name, "spec": f"{name}: {ver}", "source": "package.json", "group": key})
        except Exception as e:
            logger.warning("tools_deps: %s", e)
    return deps


def _cmd_dependency_list(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    cwd = Path(path).resolve()
    deps = []
    deps.extend(_parse_pyproject_deps(cwd))
    deps.extend(_parse_requirements(cwd))
    deps.extend(_parse_package_json(cwd))
    if not deps:
        return {"success": False, "error": f"no dependency files found in {path}"}
    return {"success": True, "data": {"dependencies": deps, "count": len(deps), "source": path}}


def _cmd_dependency_graph(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    cwd = Path(path).resolve()
    if (cwd / "pyproject.toml").exists() or (cwd / "requirements.txt").exists():
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "list", "--format=json"], capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
            packages = json.loads(r.stdout)
            return {"success": True, "data": {"packages": packages[:50], "count": len(packages)}}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "unsupported project type for graph"}


def _cmd_dependency_update(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    package = args.get("package", "")
    cwd = Path(path).resolve()
    if not package:
        return {"success": False, "error": "package is required"}
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", package], capture_output=True, text=True, timeout=TOOL_PIP_TIMEOUT)
        return {"success": r.returncode == 0, "data": {"stdout": r.stdout[-1024:], "stderr": r.stderr[-1024:], "package": package}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_install_package(args: dict, agent_id: str) -> dict:
    package = args.get("package", "")
    if not package:
        return {"success": False, "error": "package is required"}
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", package], capture_output=True, text=True, timeout=TOOL_PIP_TIMEOUT)
        return {"success": r.returncode == 0, "data": {"stdout": r.stdout[-1024:], "stderr": r.stderr[-1024:], "package": package}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_check_version(args: dict, agent_id: str) -> dict:
    package = args.get("package", "")
    if not package:
        return {"success": False, "error": "package is required"}
    try:
        import importlib.metadata
        ver = importlib.metadata.version(package)
        return {"success": True, "data": {"package": package, "version": ver, "installed": True}}
    except importlib.metadata.PackageNotFoundError:
        return {"success": True, "data": {"package": package, "version": None, "installed": False}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    register(ToolSpec(name="dependency_list", description="List project dependencies (supports pyproject.toml/requirements.txt/package.json)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")],
                      handler=_cmd_dependency_list))
    register(ToolSpec(name="dependency_graph", description="Generate dependency graph (list installed packages)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")],
                      handler=_cmd_dependency_graph))
    register(ToolSpec(name="dependency_update", description="Update specified dependency package", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("package", "string", required=True)],
                      handler=_cmd_dependency_update))
    register(ToolSpec(name="install_package", description="Install Python package", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("package", "string", required=True)],
                      handler=_cmd_install_package))
    register(ToolSpec(name="check_version", description="Check installed package version", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("package", "string", required=True)],
                      handler=_cmd_check_version))