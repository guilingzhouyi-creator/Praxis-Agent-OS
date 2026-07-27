"""Search tool handlers."""

import subprocess

from l1.kernel.params.tool import TOOL_SEARCH_TIMEOUT


def _run_grep(pattern: str, path: str, fixed: bool = False) -> list[dict]:
    """Run ripgrep (rg) with fallback to grep."""
    results = []
    cmd = ["rg", "-rn", "--no-heading", pattern, path] if not fixed else ["rg", "-rnF", "--no-heading", pattern, path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_SEARCH_TIMEOUT)
        for line in r.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 2:
                try:
                    lineno = int(parts[1])
                    text = parts[2] if len(parts) > 2 else ""
                    results.append({"file": parts[0], "line": lineno, "text": text[:200]})
                except ValueError:
                    continue
    except FileNotFoundError:
        # Fallback to grep if rg is not installed
        try:
            cmd2 = ["grep", "-rn", pattern, path]
            r = subprocess.run(cmd2, capture_output=True, text=True, timeout=TOOL_SEARCH_TIMEOUT)
            for line in r.stdout.splitlines():
                parts = line.split(":", 2)
                if len(parts) >= 2:
                    try:
                        lineno = int(parts[1])
                        text = parts[2] if len(parts) > 2 else ""
                        results.append({"file": parts[0], "line": lineno, "text": text[:200]})
                    except ValueError:
                        continue
        except Exception:
            pass
    except Exception:
        pass
    return results


def grep_search(args: dict, agent_id: str) -> dict:
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    results = _run_grep(pattern, path)
    return {"success": True, "results": results[:200], "total": len(results)}


def content_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    path = args.get("path", ".")
    if not query:
        return {"success": False, "error": "query is required"}
    results = _run_grep(query, path, fixed=True)
    return {"success": True, "results": results[:100], "total": len(results)}
