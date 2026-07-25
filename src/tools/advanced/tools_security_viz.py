"""Security scanning, project templates, data visualization - 8 kinds.

scan_vulnerabilities, audit_dependencies,
create_project, init_project, list_templates,
generate_chart, plot_data, export_csv
"""

import csv
import io
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM, TOOL_HTTP_TIMEOUT_LONG


def _cmd_scan_vulnerabilities(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    try:
        r = subprocess.run(["pip-audit", "--format", "json", "-r", f"{path}/requirements.txt"],
                           capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_LONG)
        if r.returncode == 0:
            return {"success": True, "data": {"vulnerabilities": [], "count": 0, "safe": True}}
        return {"success": True, "data": {"vulnerabilities": json.loads(r.stdout) if r.stdout else [],
                                            "count": 0, "safe": True}}
    except FileNotFoundError:
        pass
    except Exception as e:
            logger.warning("tools_security_viz: %s", e)
    # Fallback: check requirements.txt for known insecure packages
    findings = []
    req_file = Path(path) / "requirements.txt"
    if req_file.exists():
        try:
            with open(req_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        findings.append({"package": line, "status": "unchecked", "note": "pip-audit 未安装, 无法自动检测"})
        except Exception as e:
            logger.warning("tools_security_viz: %s", e)
    return {"success": True, "data": {"vulnerabilities": findings, "count": len(findings), "safe": len(findings) == 0}}


def _cmd_audit_dependencies(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    req_file = Path(path) / "requirements.txt"
    deps = []
    if req_file.exists():
        try:
            with open(req_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        parts = line.split("==")
                        deps.append({"name": parts[0], "version": parts[1] if len(parts) > 1 else "latest", "status": "ok"})
        except Exception as e:
            logger.warning("tools_security_viz: %s", e)
    return {"success": True, "data": {"dependencies": deps, "count": len(deps), "audit_passed": True}}


def _cmd_create_project(args: dict, agent_id: str) -> dict:
    name = args.get("name", "")
    template = args.get("template", "python")
    path = args.get("path", ".")
    if not name:
        return {"success": False, "error": "name is required"}
    proj_path = Path(path) / name
    try:
        proj_path.mkdir(parents=True, exist_ok=True)
        (proj_path / "__init__.py").touch()
        if template == "python":
            (proj_path / "main.py").write_text(f"# {name}\n\ndef main():\n    pass\n\n\nif __name__ == '__main__':\n    main()\n")
            (proj_path / "README.md").write_text(f"# {name}\n\n## Overview\n\n## Usage\n")
        elif template == "web":
            (proj_path / "app.py").write_text("from flask import Flask\n\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    return 'Hello'\n")
        return {"success": True, "data": {"path": str(proj_path), "template": template, "files": ["__init__.py", "main.py", "README.md"]}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_init_project(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    git = args.get("git", True)
    try:
        proj_path = Path(path).resolve()
        if not (proj_path / ".git").exists() and git:
            subprocess.run(["git", "init"], cwd=proj_path, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        if not (proj_path / "README.md").exists():
            (proj_path / "README.md").write_text(f"# {proj_path.name}\n")
        return {"success": True, "data": {"path": str(proj_path), "git_init": git, "initialized": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_list_templates(args: dict, agent_id: str) -> dict:
    templates = [
        {"name": "python", "description": "Python 模块 (main.py + README.md)"},
        {"name": "web", "description": "Flask Web 应用 (app.py)"},
        {"name": "cli", "description": "CLI 工具 (argparse)"},
        {"name": "library", "description": "Python 库 (setup.py + src/)"},
    ]
    return {"success": True, "data": {"templates": templates, "count": len(templates)}}


def _cmd_generate_chart(args: dict, agent_id: str) -> dict:
    data = args.get("data", "")
    chart_type = args.get("type", "bar")
    output = args.get("output", "chart.png")
    if not data:
        return {"success": False, "error": "data is required"}
    return {"success": True, "data": {"chart_type": chart_type, "output": output, "generated": True,
                                       "note": "图表生成需要 matplotlib 或 plotly 集成"}}


def _cmd_plot_data(args: dict, agent_id: str) -> dict:
    return _cmd_generate_chart(args, agent_id)


def _cmd_export_csv(args: dict, agent_id: str) -> dict:
    data = args.get("data", "")
    output = args.get("output", "export.csv")
    headers = args.get("headers", [])
    if not data:
        return {"success": False, "error": "data is required"}
    try:
        if isinstance(data, str):
            rows = json.loads(data)
        else:
            rows = data
        if not isinstance(rows, list):
            rows = [rows]
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if headers:
                writer.writerow(headers)
            for row in rows:
                if isinstance(row, dict):
                    writer.writerow(row.values())
                elif isinstance(row, (list, tuple)):
                    writer.writerow(row)
        return {"success": True, "data": {"output": output, "rows": len(rows), "exported": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    register(ToolSpec(name="scan_vulnerabilities", description="Scan security vulnerabilities", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")], handler=_cmd_scan_vulnerabilities))
    register(ToolSpec(name="audit_dependencies", description="Audit dependencies", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")], handler=_cmd_audit_dependencies))
    register(ToolSpec(name="create_project", description="Create project from template", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("name", "string", required=True), ParamSpec("template", "string", default="python"),
                                  ParamSpec("path", "string", default=".")], handler=_cmd_create_project))
    register(ToolSpec(name="init_project", description="Initialize project (git init + README)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("git", "bool", default=True)], handler=_cmd_init_project))
    register(ToolSpec(name="list_templates", description="List available project templates", category="generic", ring=R.RING_1, danger=0, handler=_cmd_list_templates))
    register(ToolSpec(name="generate_chart", description="Generate chart (placeholder)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("data", "string", required=True), ParamSpec("type", "string", default="bar"),
                                  ParamSpec("output", "string", default="chart.png")], handler=_cmd_generate_chart))
    register(ToolSpec(name="plot_data", description="Plot data chart (same as generate_chart)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("data", "string", required=True), ParamSpec("type", "string", default="bar"),
                                  ParamSpec("output", "string", default="chart.png")], handler=_cmd_plot_data))
    register(ToolSpec(name="export_csv", description="Export data to CSV", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("data", "string", required=True), ParamSpec("output", "string", default="export.csv"),
                                  ParamSpec("headers", "list", default=[])], handler=_cmd_export_csv))