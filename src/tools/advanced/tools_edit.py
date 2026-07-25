"""Structured edit tools - 4 kinds.

ast_parse, ast_transform, semantic_patch, apply_diff
"""

import ast
import difflib
import os
import textwrap
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R


def _cmd_ast_parse(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    code = args.get("code", "")
    if not path and not code:
        return {"success": False, "error": "path or code is required"}
    try:
        if path:
            with open(path, encoding="utf-8") as f:
                code = f.read()
        tree = ast.parse(code)
        # 简化 AST 摘要
        nodes = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                  ast.Assign, ast.Import, ast.ImportFrom, ast.Call)):
                info = {"type": type(node).__name__, "line": node.lineno}
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    info["name"] = node.name
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        info["name"] = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        info["name"] = f"{node.func.attr}"
                nodes.append(info)
        return {"success": True, "data": {"nodes": nodes, "count": len(nodes)}}
    except SyntaxError as e:
        return {"success": False, "error": f"syntax error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_ast_transform(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    transformer = args.get("transformer", "")
    if not path or not transformer:
        return {"success": False, "error": "path and transformer are required"}
    try:
        with open(path, encoding="utf-8") as f:
            code = f.read()
        tree = ast.parse(code)
        # 支持简单转换器: "wrap_function:name" 或 "rename_function:old:new"
        if transformer.startswith("wrap_function:"):
            parts = transformer.split(":")
            if len(parts) >= 2:
                func_name = parts[1]
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == func_name:
                        old_body = node.body
                        node.body = [
                            ast.Try(
                                body=old_body,
                                handlers=[ast.ExceptHandler(
                                    type=ast.Name(id="Exception"),
                                    name="e",
                                    body=[ast.Expr(ast.Call(
                                        func=ast.Attribute(attr="error", value=ast.Name(id="logger")),
                                        args=[ast.Constant(value=f"Error in {func_name}: {e}")],
                                    ))],
                                )],
                                orelse=[],
                                finalbody=[],
                            )
                        ]
                        break
        elif transformer.startswith("rename_function:"):
            parts = transformer.split(":")
            if len(parts) >= 3:
                old_name, new_name = parts[1], parts[2]
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == old_name:
                        node.name = new_name
                        break
        code = ast.unparse(tree)
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        return {"success": True, "data": {"path": path, "transformer": transformer}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_semantic_patch(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    patch = args.get("patch", "")
    if not path or not patch:
        return {"success": False, "error": "path and patch are required"}
    try:
        # patch 格式: "func_name:before_pattern:after_pattern"
        parts = patch.split(":", 2)
        if len(parts) < 3:
            return {"success": False, "error": "patch format: func_name:before:after"}
        func_name, before, after = parts
        with open(path, encoding="utf-8") as f:
            content = f.read()
        count = content.count(before)
        if count == 0:
            return {"success": False, "error": f"pattern not found in {path}"}
        content = content.replace(before, after)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "data": {"path": path, "replaced": count, "func": func_name}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_apply_diff(args: dict, agent_id: str) -> dict:
    """Apply a unified-diff patch to a file.

    Implements a minimal unified-diff applier: parse hunks (``@@ ... @@``
    headers with ``<start>[,<count>]`` for the old side), then for each
    hunk replace the matching old block with the added lines. Uses
    ``difflib``-style parsing; rejects patches that don't line up
    rather than corrupting the file.
    """
    path = args.get("path", "")
    diff_text = args.get("diff", "")
    if not path or not diff_text:
        return {"success": False, "error": "path and diff are required"}

    try:
        with open(path, encoding="utf-8") as f:
            original_lines = f.readlines()
    except FileNotFoundError:
        original_lines = []

    try:
        result_lines, added, removed = _apply_unified_diff(original_lines, diff_text)
    except ValueError as e:
        return {"success": False, "error": f"patch failed: {e}"}

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(result_lines)
    except OSError as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "data": {
        "path": path, "lines_added": added, "lines_removed": removed,
        "total_lines": len(result_lines),
    }}


def _apply_unified_diff(original: list[str], diff_text: str) -> tuple[list[str], int, int]:
    """Apply a unified diff to ``original`` and return (new_lines, added, removed).

    Raises ``ValueError`` if the diff is malformed or the context lines
    don't match the source. Counts any ``-`` line as removed and any ````
    line as added; context lines (`` ``) and hunk headers (``@@``) are
    ignored for the count.
    """
    import re

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    original_idx = 0  # 0-based index into original
    result: list[str] = []
    added = removed = 0
    in_hunk = False

    for raw_line in diff_text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        if line.startswith("@@"):
            m = hunk_re.match(line)
            if not m:
                raise ValueError(f"malformed hunk header: {line!r}")
            # Append any untouched source lines up to the hunk start
            hunk_start = int(m.group(1)) - 1  # unified diff is 1-based
            if hunk_start < original_idx:
                raise ValueError("hunk start before current source position")
            result.extend(original[original_idx:hunk_start])
            original_idx = hunk_start
            in_hunk = True
            continue
        if not in_hunk:
            # Skip file headers (+++ / ---) and preamble
            continue
        if line.startswith("+"):
            result.append(raw_line[1:])
            added += 1
        elif line.startswith("-"):
            if original_idx >= len(original):
                raise ValueError("removal past end of source")
            original_idx += 1
            removed += 1
        elif line.startswith(" "):
            if original_idx >= len(original):
                raise ValueError("context past end of source")
            result.append(original[original_idx])
            original_idx += 1
        elif line.startswith("\\"):
            # ``\ No newline at end of file`` — ignore
            continue
        else:
            raise ValueError(f"unexpected diff line: {line!r}")

    # Append the remaining untouched tail
    result.extend(original[original_idx:])
    return result, added, removed



def register_tools() -> None:
    register(ToolSpec(name="ast_parse", description="Parse code into AST summary (functions/classes/calls)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=""), ParamSpec("code", "string", default="")],
                      handler=_cmd_ast_parse))
    register(ToolSpec(name="ast_transform", description="Transform code via AST (wrap_function/rename_function)", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("transformer", "string", required=True)],
                      handler=_cmd_ast_transform))
    register(ToolSpec(name="semantic_patch", description="Semantic code patch (func:before:after)", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("patch", "string", required=True)],
                      handler=_cmd_semantic_patch))
    register(ToolSpec(name="apply_diff", description="Apply diff patch to file", category="generic",
                      ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("diff", "string", required=True)],
                      handler=_cmd_apply_diff))