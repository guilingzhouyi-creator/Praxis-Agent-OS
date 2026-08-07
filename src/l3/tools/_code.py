"""Code analysis handlers."""

import logging
import os
import re

from l1.kernel.params.system import (
    LOG_TRUNC_30,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    TOOL_ISSUES_LIMIT,
    TOOL_RESULTS_LIMIT_DEFAULT,
    TOOL_RESULTS_LIMIT_LARGE,
)

logger = logging.getLogger(__name__)


def symbol_search(args: dict, agent_id: str) -> dict:
    """Search for symbol definitions (def/class/function) under path; returns matches."""
    symbol = args.get("symbol", "")
    path = args.get("path", ".")
    if not symbol:
        return {"success": False, "error": "symbol is required"}
    results = []
    pattern = re.compile(r"(def |class |async def |fn |func |function )\s*" + re.escape(symbol))
    for root, _dirs, files in os.walk(path):
        for f in files:
            if not f.endswith((".py", ".rs", ".ts", ".js", ".go", ".java")):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if pattern.search(line):
                            results.append({"file": fp, "line": lineno, "text": line.strip()[:LOG_TRUNC_200]})
            except Exception:
                logger.debug("_code: symbol_search file read failed")
    return {"success": True, "results": results[:TOOL_RESULTS_LIMIT_DEFAULT], "total": len(results)}


def find_imports(args: dict, agent_id: str) -> dict:
    """Scan Python files under path for import statements; returns matches."""
    path = args.get("path", ".")
    results = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            if not f.endswith(".py"):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if line.startswith("import ") or line.startswith("from "):
                            results.append({"file": fp, "line": lineno, "text": line.strip()})
            except Exception:
                logger.debug("_code: find_imports file read failed")
    return {"success": True, "results": results[:TOOL_RESULTS_LIMIT_LARGE], "total": len(results)}


def review_code(args: dict, agent_id: str) -> dict:
    """Lint a file for line length, TODO, and bare except issues; returns issues."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    issues = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return {"success": False, "error": str(e)}
    for i, line in enumerate(lines, 1):
        if len(line) > 120:
            issues.append({"line": i, "type": "line_length", "message": f"Line too long ({len(line)} chars)"})
        if "TODO" in line:
            issues.append({"line": i, "type": "todo", "message": line.strip()[:LOG_TRUNC_100]})
        if line.strip().startswith("except:") or line.strip().startswith("except :"):
            issues.append({"line": i, "type": "bare_except", "message": "Bare except clause"})
    return {"success": True, "issues": issues[:TOOL_ISSUES_LIMIT], "total": len(issues), "file": path}


def list_functions(args: dict, agent_id: str) -> dict:
    """RING_1: List all function/class/method definitions in a Python file."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    results = []
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        return {"success": False, "error": str(e)}
    for m in re.finditer(r"^(async\s+)?(def |class )\s*(\w+)", source, re.MULTILINE):
        kind = "class" if "class" in m.group(2) else "function"
        is_async = "async" in (m.group(1) or "")
        results.append(
            {"name": m.group(3), "kind": kind, "async": is_async, "line": source[: m.start()].count("\n") + 1}
        )
    return {"success": True, "functions": results, "total": len(results), "file": path}


def ast_parse(args: dict, agent_id: str) -> dict:
    """RING_1: Parse a Python file into its top-level AST structure."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        import ast

        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        nodes = []
        for node in ast.iter_child_nodes(tree):
            entry = {"type": type(node).__name__, "line": getattr(node, "lineno", 0)}
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                entry["name"] = node.name
            nodes.append(entry)
        return {"success": True, "nodes": nodes, "total": len(nodes), "file": path}
    except SyntaxError as e:
        return {"success": False, "error": f"syntax error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def find_callees(args: dict, agent_id: str) -> dict:
    """RING_1: Extract all function/method call expressions from a Python file."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        import ast

        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)

        class _CallVisitor(ast.NodeVisitor):
            """_CallVisitor — _ call visitor."""

            def __init__(self):
                self.calls = []

            def visit_Call(self, node):  # noqa: N802
                """Record a function call node and continue the traversal."""
                if isinstance(node.func, ast.Name):
                    self.calls.append({"name": node.func.id, "line": node.lineno})
                elif isinstance(node.func, ast.Attribute):
                    self.calls.append(
                        {
                            "name": f"{node.func.attr}",
                            "obj": ast.unparse(node.func.value)[:LOG_TRUNC_30],
                            "line": node.lineno,
                        }
                    )
                self.generic_visit(node)

        visitor = _CallVisitor()
        visitor.visit(tree)
        return {
            "success": True,
            "calls": visitor.calls[:TOOL_RESULTS_LIMIT_DEFAULT],
            "total": len(visitor.calls),
            "file": path,
        }
    except SyntaxError as e:
        return {"success": False, "error": f"syntax error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
