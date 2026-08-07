"""Search tool handlers — cross-platform with pure Python fallback."""

import logging
import os
import re
import subprocess

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.system import LOG_TRUNC_200, TOOL_RESULTS_LIMIT_DEFAULT, TOOL_RESULTS_LIMIT_LARGE

logger = logging.getLogger(__name__)


def _py_grep(pattern: str, path: str, fixed: bool = False) -> list[dict]:
    """Pure Python search fallback for platforms without rg/grep."""
    results: list[dict] = []
    if os.path.isfile(path):
        # Search a single file directly
        files_to_scan = [path]
    elif os.path.isdir(path):
        files_to_scan = []
        for root, _dirs, files in os.walk(path):
            for fname in files:
                files_to_scan.append(os.path.join(root, fname))
    else:
        return results
    try:
        for fp in files_to_scan:
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if fixed:
                            matched = pattern in line
                        else:
                            try:
                                matched = re.search(pattern, line) is not None
                            except re.error:
                                continue
                        if matched:
                            results.append({"file": fp, "line": lineno, "text": line.rstrip()[:LOG_TRUNC_200]})
            except (OSError, UnicodeDecodeError):
                continue
    except Exception:
        logger.debug("_search: _py_grep walk failed")
    return results


def _run_grep(pattern: str, path: str, fixed: bool = False) -> list[dict]:
    """Run the platform-appropriate grep command, then pure Python fallback.

    Uses ``l1.kernel.platform.grep_cmd()`` for cross-platform command
    selection (rg → grep/findstr); falls back to pure Python only when
    the command itself fails (per project convention, no hand-rolled
    platform dispatch in implementation code).
    """
    from l1.kernel.platform import grep_cmd

    try:
        cmd = grep_cmd(pattern, path, fixed=fixed)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=get_tool_config("search_timeout", 30))
        if r.returncode == 0:
            return _parse_grep_output(r.stdout.splitlines())
        logger.debug("_search: grep_cmd returned %s", r.returncode)
    except Exception:
        logger.debug("_search: grep_cmd run failed, falling back to pure Python")
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
                results.append({"file": parts[0], "line": lineno, "text": text[:LOG_TRUNC_200]})
            except ValueError:
                continue
    return results


def file_search(args: dict, agent_id: str) -> dict:
    """Search file names by pattern (not content)."""
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    results = []
    for root, _dirs, files in os.walk(path):
        for fname in files:
            if pattern in fname or re.search(pattern, fname):
                results.append(os.path.join(root, fname))
    return {"success": True, "results": results[:TOOL_RESULTS_LIMIT_LARGE], "total": len(results)}


def grep_search(args: dict, agent_id: str) -> dict:
    """Search file contents by regex pattern under path; returns match dict."""
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    results = _run_grep(pattern, path)
    return {"success": True, "results": results[:TOOL_RESULTS_LIMIT_LARGE], "total": len(results)}


def content_search(args: dict, agent_id: str) -> dict:
    """Search file contents for fixed text under path; returns match dict."""
    query = args.get("query", "")
    path = args.get("path", ".")
    if not query:
        return {"success": False, "error": "query is required"}
    results = _run_grep(query, path, fixed=True)
    return {"success": True, "results": results[:TOOL_RESULTS_LIMIT_DEFAULT], "total": len(results)}
