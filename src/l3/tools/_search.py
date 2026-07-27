"""Search tool handlers — cross-platform with pure Python fallback."""

import os
import re
import subprocess

from l1.kernel.params.tool import TOOL_SEARCH_TIMEOUT


def _py_grep(pattern: str, path: str, fixed: bool = False) -> list[dict]:
    """Pure Python search fallback for platforms without rg/grep."""
    results = []
    if not os.path.isdir(path):
        path = os.path.dirname(path) or "."
    try:
        for root, dirs, files in os.walk(path):
            for fname in files:
                fp = os.path.join(root, fname)
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if fixed:
                                matched = pattern in line
                            else:
                                try:
                                    matched = re.search(pattern, line)
                                except re.error:
                                    continue
                            if matched:
                                results.append({"file": fp, "line": lineno, "text": line.rstrip()[:200]})
                except (OSError, UnicodeDecodeError):
                    continue
    except Exception:
        pass
    return results


def _run_grep(pattern: str, path: str, fixed: bool = False) -> list[dict]:
    """Run ripgrep (rg) with fallback to grep, then pure Python."""
    # Try rg first
    cmd = ["rg", "-rn", "--no-heading", pattern, path] if not fixed else ["rg", "-rnF", "--no-heading", pattern, path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_SEARCH_TIMEOUT)
        if r.returncode == 0:
            return _parse_grep_output(r.stdout.splitlines())
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # Fallback to grep
    try:
        cmd2 = ["grep", "-rn", pattern, path]
        r = subprocess.run(cmd2, capture_output=True, text=True, timeout=TOOL_SEARCH_TIMEOUT)
        if r.returncode == 0:
            return _parse_grep_output(r.stdout.splitlines())
    except Exception:
        pass
    # Pure Python fallback (works on all platforms)
    return _py_grep(pattern, path, fixed=fixed)


def _parse_grep_output(lines: list[str]) -> list[dict]:
    """Parse rg/grep output lines into structured results."""
    results = []
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) >= 2:
            try:
                lineno = int(parts[1])
                text = parts[2] if len(parts) > 2 else ""
                results.append({"file": parts[0], "line": lineno, "text": text[:200]})
            except ValueError:
                continue
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
