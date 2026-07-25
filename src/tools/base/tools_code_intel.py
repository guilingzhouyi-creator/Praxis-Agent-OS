"""Code intelligence tools - 12 kinds.

symbol_search, reference_search, definition_search, implementation_search,
type_search, code_complete, hover_info, diagnostics, format_code, lint_code,
rename_symbol, find_imports
"""

import ast
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM, TOOL_HTTP_TIMEOUT_LONG
from kernel.platform import IS_NT, IS_WINDOWS, grep_cmd


def _run_pyright(args: list[str]) -> dict:
    """Run pyright type checker."""
    try:
        r = subprocess.run(["pyright"] + args, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_LONG)
        return {"success": True, "stdout": r.stdout, "stderr": r.stderr, "code": r.returncode}
    except FileNotFoundError:
        return {"success": False, "error": "pyright not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _simple_parse_symbols(file_path: str) -> list[dict]:
    """Simple AST-based symbol parsing."""
    symbols = []
    try:
        with open(file_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({
                    "name": node.name, "type": "function",
                    "line": node.lineno, "end_line": node.end_lineno,
                })
            elif isinstance(node, ast.ClassDef):
                symbols.append({
                    "name": node.name, "type": "class",
                    "line": node.lineno, "end_line": node.end_lineno,
                })
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        symbols.append({
                            "name": target.id, "type": "variable",
                            "line": node.lineno,
                        })
    except Exception as e:
            logger.warning("tools_code_intel: %s", e)
    return symbols


def _cmd_symbol_search(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    name = args.get("name", "")
    kind = args.get("kind", "")
    results = []
    p = Path(path)
    for f in p.rglob("*.py"):
        if f.name.startswith("__") or ".venv" in str(f):
            continue
        syms = _simple_parse_symbols(str(f))
        for s in syms:
            if name and name not in s["name"]:
                continue
            if kind and s["type"] != kind:
                continue
            results.append({"file": str(f), **s})
    return {"success": True, "data": {"symbols": results[:50], "count": len(results)}}


def _cmd_reference_search(args: dict, agent_id: str) -> dict:
    name = args.get("name", "")
    path = args.get("path", ".")
    if not name:
        return {"success": False, "error": "name is required"}
    try:
        cmd = grep_cmd(name, path, file_type="py")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:50]
        return {"success": True, "data": {"references": lines, "count": len(lines), "symbol": name}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_definition_search(args: dict, agent_id: str) -> dict:
    return _cmd_symbol_search({"path": args.get("path", "."), "name": args.get("name", ""), "kind": ""}, agent_id)


def _cmd_implementation_search(args: dict, agent_id: str) -> dict:
    return _cmd_symbol_search({"path": args.get("path", "."), "name": args.get("name", ""), "kind": ""}, agent_id)


def _cmd_type_search(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    type_name = args.get("type_name", "")
    if not type_name:
        return {"success": False, "error": "type_name is required"}
    try:
        cmd = grep_cmd(type_name, path, file_type="py")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:50]
        return {"success": True, "data": {"results": lines, "count": len(lines), "type": type_name}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_code_complete(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    line = args.get("line", 1)
    column = args.get("column", 1)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        r = _run_pyright(["--completion", f"{path}:{line}:{column}"])
        return r
    except Exception as e:
        return {"success": False, "error": f"pyright completion failed: {e}"}


def _cmd_hover_info(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    line = args.get("line", 1)
    column = args.get("column", 1)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        r = _run_pyright(["--hover", f"{path}:{line}:{column}"])
        return r
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_diagnostics(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    try:
        r = _run_pyright([path])
        return r
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_format_code(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        subprocess.run(["black", "--quiet", path], capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        return {"success": True, "data": {"formatted": path, "formatter": "black"}}
    except FileNotFoundError:
        try:
            subprocess.run(["autopep8", "--in-place", path], capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
            return {"success": True, "data": {"formatted": path, "formatter": "autopep8"}}
        except Exception as e:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_lint_code(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    try:
        r = subprocess.run(["ruff", "check", path], capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        return {"success": True, "data": {"output": r.stdout, "stderr": r.stderr, "issues": r.returncode}}
    except FileNotFoundError:
        try:
            r = subprocess.run(["pylint", path], capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
            return {"success": True, "data": {"output": r.stdout, "stderr": r.stderr, "issues": r.returncode}}
        except Exception as e:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_rename_symbol(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    old_name = args.get("old_name", "")
    new_name = args.get("new_name", "")
    if not path or not old_name or not new_name:
        return {"success": False, "error": "path, old_name, new_name are required"}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_name)
        if count == 0:
            return {"success": False, "error": f"'{old_name}' not found in {path}"}
        content = content.replace(old_name, new_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "data": {"path": path, "old": old_name, "new": new_name, "replaced": count}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_find_imports(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    module = args.get("module", "")
    results = []
    p = Path(path)
    for f in p.rglob("*.py"):
        if f.name.startswith("__") or ".venv" in str(f):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    if module:
                        if module in line and ("import" in line or "from" in line):
                            results.append({"file": str(f), "line": line.strip()})
                    else:
                        if line.strip().startswith(("import ", "from ")):
                            results.append({"file": str(f), "line": line.strip()})
        except Exception as e:
            logger.warning("tools_code_intel: %s", e)
    return {"success": True, "data": {"imports": results[:100], "count": len(results)}}


def register_tools() -> None:
    register(ToolSpec(name="symbol_search", description="Search code for symbol definitions (functions/classes/variables)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("name", "string", default=""), ParamSpec("kind", "string", default="")],
                      handler=_cmd_symbol_search))
    register(ToolSpec(name="reference_search", description="Search all reference locations of a symbol", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("name", "string", required=True), ParamSpec("path", "string", default=".")],
                      handler=_cmd_reference_search))
    register(ToolSpec(name="definition_search", description="Search definition location of a symbol", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("name", "string", default=""), ParamSpec("path", "string", default=".")],
                      handler=_cmd_definition_search))
    register(ToolSpec(name="implementation_search", description="Search implementations of interfaces/abstract methods", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("name", "string", default=""), ParamSpec("path", "string", default=".")],
                      handler=_cmd_implementation_search))
    register(ToolSpec(name="type_search", description="Search type references", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("type_name", "string", required=True), ParamSpec("path", "string", default=".")],
                      handler=_cmd_type_search))
    register(ToolSpec(name="code_complete", description="Get code completion suggestions (requires pyright)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("line", "int", default=1), ParamSpec("column", "int", default=1)],
                      handler=_cmd_code_complete))
    register(ToolSpec(name="hover_info", description="Get hover information (requires pyright)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("line", "int", default=1), ParamSpec("column", "int", default=1)],
                      handler=_cmd_hover_info))
    register(ToolSpec(name="diagnostics", description="Run type checker for diagnostics", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")],
                      handler=_cmd_diagnostics))
    register(ToolSpec(name="format_code", description="Format code (black/autopep8)", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True)],
                      handler=_cmd_format_code))
    register(ToolSpec(name="lint_code", description="Run linter for code quality (ruff/pylint)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")],
                      handler=_cmd_lint_code))
    register(ToolSpec(name="rename_symbol", description="Rename symbol (text replacement)", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("old_name", "string", required=True), ParamSpec("new_name", "string", required=True)],
                      handler=_cmd_rename_symbol))
    register(ToolSpec(name="find_imports", description="Find import statements in files", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default="."), ParamSpec("module", "string", default="")],
                      handler=_cmd_find_imports))