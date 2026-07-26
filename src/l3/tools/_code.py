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
