"""Search tool handlers."""

import os
import re


def grep_search(args: dict, agent_id: str) -> dict:
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    results = []
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                with open(fp, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if re.search(pattern, line):
                            results.append({"file": fp, "line": lineno, "text": line.rstrip()[:200]})
            except Exception:
                pass
    return {"success": True, "results": results[:200], "total": len(results)}


def content_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    path = args.get("path", ".")
    if not query:
        return {"success": False, "error": "query is required"}
    results = []
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                with open(fp, encoding="utf-8") as fh:
                    content = fh.read()
                    if query.lower() in content.lower():
                        results.append({"file": fp, "size": len(content)})
            except Exception:
                pass
    return {"success": True, "results": results[:100], "total": len(results)}
