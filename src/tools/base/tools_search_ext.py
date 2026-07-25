"""Search enhancement tools - 5 kinds.

semantic_search, regex_search, file_type_search, content_search, grep_search (增强)
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM
from kernel.platform import IS_NT, IS_WINDOWS, grep_cmd


def _cmd_semantic_search(args: dict, agent_id: str) -> dict:
    """Semantic search - simple keyword-based, vector search can be added later."""
    query = args.get("query", "")
    path = args.get("path", ".")
    max_results = args.get("max_results", 20)
    if not query:
        return {"success": False, "error": "query is required"}
    keywords = query.lower().split()
    results = []
    p = Path(path)
    for f in p.rglob("*.py"):
        if ".venv" in str(f) or f.name.startswith("__"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                content = fh.read().lower()
            score = sum(content.count(kw) for kw in keywords)
            if score > 0:
                results.append({"file": str(f), "score": score, "path": str(f)})
        except Exception as e:
            logger.warning("tools_search_ext: %s", e)
    results.sort(key=lambda x: -x["score"])
    return {"success": True, "data": {"results": results[:max_results], "count": len(results)}}


def _cmd_regex_search(args: dict, agent_id: str) -> dict:
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    file_pattern = args.get("file_pattern", "*")
    max_results = args.get("max_results", 50)
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    try:
        cmd = grep_cmd(pattern, path, max_count=max_results, glob_pattern=file_pattern)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:max_results]
        return {"success": True, "data": {"results": lines, "count": len(lines), "pattern": pattern}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_file_type_search(args: dict, agent_id: str) -> dict:
    ext = args.get("extension", "")
    path = args.get("path", ".")
    if not ext:
        return {"success": False, "error": "extension is required"}
    ext = ext if ext.startswith(".") else f".{ext}"
    results = []
    p = Path(path)
    for f in p.rglob(f"*{ext}"):
        if ".venv" in str(f):
            continue
        try:
            s = os.stat(f)
            results.append({"file": str(f), "size": s.st_size, "modified": s.st_mtime})
        except Exception as e:
            logger.warning("tools_search_ext: %s", e)
    results.sort(key=lambda x: -x["size"])
    return {"success": True, "data": {"results": results[:100], "count": len(results), "extension": ext}}


def _cmd_content_search(args: dict, agent_id: str) -> dict:
    """Content search - search file contents (case-sensitive/insensitive)."""
    query = args.get("query", "")
    path = args.get("path", ".")
    case_sensitive = args.get("case_sensitive", False)
    max_results = args.get("max_results", 50)
    if not query:
        return {"success": False, "error": "query is required"}
    try:
        cmd = grep_cmd(query, path, ignore_case=not case_sensitive, max_count=max_results)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:max_results]
        return {"success": True, "data": {"results": lines, "count": len(lines), "query": query}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_grep_search_enhanced(args: dict, agent_id: str) -> dict:
    """Enhanced grep - context lines, include/exclude patterns."""
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    context = args.get("context", 0)
    include = args.get("include", "")
    exclude = args.get("exclude", "")
    max_results = args.get("max_results", 100)
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    try:
        cmd = grep_cmd(pattern, path, max_count=max_results, glob_pattern=include)
        if cmd[0] == "rg":
            if context > 0:
                cmd.extend(["-C", str(context)])
            if exclude:
                cmd.extend(["--glob", f"!{exclude}"])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:max_results]
        return {"success": True, "data": {"results": lines, "count": len(lines), "pattern": pattern}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    register(ToolSpec(name="semantic_search", description="Semantic search file content (sorted by keyword relevance)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("query", "string", required=True), ParamSpec("path", "string", default="."),
                                  ParamSpec("max_results", "int", default=20)],
                      handler=_cmd_semantic_search))
    register(ToolSpec(name="regex_search", description="Regex search file content", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("pattern", "string", required=True), ParamSpec("path", "string", default="."),
                                  ParamSpec("file_pattern", "string", default="*"), ParamSpec("max_results", "int", default=50)],
                      handler=_cmd_regex_search))
    register(ToolSpec(name="file_type_search", description="Search by file type (extension)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("extension", "string", required=True), ParamSpec("path", "string", default=".")],
                      handler=_cmd_file_type_search))
    register(ToolSpec(name="content_search", description="Search file content (case sensitive/insensitive)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("query", "string", required=True), ParamSpec("path", "string", default="."),
                                  ParamSpec("case_sensitive", "bool", default=False), ParamSpec("max_results", "int", default=50)],
                      handler=_cmd_content_search))
    register(ToolSpec(name="grep_search_enhanced", description="Enhanced grep search (with context/include/exclude)", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("pattern", "string", required=True), ParamSpec("path", "string", default="."),
                                  ParamSpec("context", "int", default=0), ParamSpec("include", "string", default=""),
                                  ParamSpec("exclude", "string", default=""), ParamSpec("max_results", "int", default=100)],
                      handler=_cmd_grep_search_enhanced))