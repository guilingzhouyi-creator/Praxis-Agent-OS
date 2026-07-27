"""Code analysis handlers."""

import os
import re


def symbol_search(args: dict, agent_id: str) -> dict:
    symbol = args.get("symbol", "")
    path = args.get("path", ".")
    if not symbol:
        return {"success": False, "error": "symbol is required"}
    results = []
    pattern = re.compile(r'(def |class |async def |fn |func |function )\s*' + re.escape(symbol))
    for root, dirs, files in os.walk(path):
        for f in files:
            if not f.endswith((".py", ".rs", ".ts", ".js", ".go", ".java")):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if pattern.search(line):
                            results.append({"file": fp, "line": lineno, "text": line.strip()[:200]})
            except Exception:
                pass
    return {"success": True, "results": results[:100], "total": len(results)}


def find_imports(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    results = []
    for root, dirs, files in os.walk(path):
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
                pass
    return {"success": True, "results": results[:200], "total": len(results)}


def review_code(args: dict, agent_id: str) -> dict:
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
            issues.append({"line": i, "type": "todo", "message": line.strip()[:100]})
        if line.strip().startswith("except:") or line.strip().startswith("except :"):
            issues.append({"line": i, "type": "bare_except", "message": "Bare except clause"})
    return {"success": True, "issues": issues[:50], "total": len(issues), "file": path}


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
    for m in re.finditer(r'^(async\s+)?(def |class )\s*(\w+)', source, re.MULTILINE):
        kind = "class" if "class" in m.group(2) else "function"
        is_async = "async" in (m.group(1) or "")
        results.append({"name": m.group(3), "kind": kind, "async": is_async,
                        "line": source[:m.start()].count("\n") + 1})
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
            entry = {"type": type(node).__name__, "line": node.lineno}
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
            def __init__(self):
                self.calls = []
            def visit_Call(self, node):  # noqa: N802
                if isinstance(node.func, ast.Name):
                    self.calls.append({"name": node.func.id, "line": node.lineno})
                elif isinstance(node.func, ast.Attribute):
                    self.calls.append({"name": f"{node.func.attr}", "obj": ast.unparse(node.func.value)[:30],
                                       "line": node.lineno})
                self.generic_visit(node)
        visitor = _CallVisitor()
        visitor.visit(tree)
        return {"success": True, "calls": visitor.calls[:100], "total": len(visitor.calls), "file": path}
    except SyntaxError as e:
        return {"success": False, "error": f"syntax error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
