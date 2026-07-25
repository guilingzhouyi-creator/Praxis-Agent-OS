"""Agent OS extension tools - 6 new tools (Phase 3).

Bridging capability gaps with Claude Code / Codex:
git_commit, git_push, git_branch, web_fetch, project_tree, env_query
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from constants import TOOL_HTTP_TIMEOUT_MEDIUM, TOOL_HTTP_TIMEOUT_LONG

# ═════════════════════════════════════════════════════════════════════════════
# Git tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_git_commit(args: dict, agent_id: str) -> dict:
    """Commit code changes."""
    message = args.get("message", "")
    files = args.get("files", [])
    if not message:
        return {"success": False, "error": "message is required"}
    try:
        if files:
            subprocess.run(["git", "add"] + files, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        else:
            subprocess.run(["git", "add", "-A"], capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        r = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM,
        )
        return {
            "success": r.returncode == 0,
            "data": {"stdout": r.stdout, "stderr": r.stderr},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_git_push(args: dict, agent_id: str) -> dict:
    """Push commits to remote."""
    remote = args.get("remote", "origin")
    branch = args.get("branch", "")
    try:
        cmd = ["git", "push", remote]
        if branch:
            cmd.append(branch)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_LONG)
        return {
            "success": r.returncode == 0,
            "data": {"stdout": r.stdout, "stderr": r.stderr},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_git_branch(args: dict, agent_id: str) -> dict:
    """Create/switch/delete branch."""
    action = args.get("action", "")
    name = args.get("name", "")
    if not action or not name:
        return {"success": False, "error": "action and name are required"}
    try:
        cmd_map = {
            "create": ["git", "branch", name],
            "switch": ["git", "checkout", name],
            "delete": ["git", "branch", "-D", name],
        }
        cmd = cmd_map.get(action)
        if not cmd:
            return {"success": False, "error": f"unknown action: {action}"}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        return {
            "success": r.returncode == 0,
            "data": {"stdout": r.stdout, "stderr": r.stderr},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Web tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_web_fetch(args: dict, agent_id: str) -> dict:
    """Fetch web page content."""
    url = args.get("url", "")
    max_chars = args.get("max_chars", 5000)
    if not url:
        return {"success": False, "error": "url is required"}
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": HTTP_TOOL_USER_AGENT})
        with urllib.request.urlopen(req, timeout=TOOL_HTTP_TIMEOUT_MEDIUM) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        if max_chars and len(content) > max_chars:
            content = content[:max_chars] + "\n... (truncated)"
        return {"success": True, "data": content}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Project and environment tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_project_tree(args: dict, agent_id: str) -> dict:
    """Get project structure tree and file stats."""
    path = args.get("path", ".")
    depth = args.get("depth", 3)
    try:
        root = Path(path).resolve()
        tree = _build_tree(root, depth)
        stats = _count_files(root)
        return {"success": True, "data": {"tree": tree, "stats": stats}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _build_tree(root: Path, depth: int, prefix: str = "") -> list[str]:
    """Recursively build directory tree."""
    if depth <= 0:
        return [f"{prefix}└── ..."]
    lines = []
    try:
        entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        for i, entry in enumerate(entries):
            if entry.name.startswith(".") or entry.name.startswith("__"):
                continue
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                ext = "    " if is_last else "│   "
                lines.extend(_build_tree(entry, depth - 1, prefix + ext))
    except PermissionError:
        lines.append(f"{prefix}└── [permission denied]")
    return lines[:50]  # 最多 50 行


def _count_files(root: Path) -> dict:
    """Count files."""
    total = 0
    by_ext = {}
    try:
        for f in root.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                total += 1
                ext = f.suffix or "(no ext)"
                by_ext[ext] = by_ext.get(ext, 0) + 1
    except PermissionError:
        pass
    return {"total": total, "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])[:10])}


def _cmd_env_query(args: dict, agent_id: str) -> dict:
    """Query environment info."""
    key = args.get("key", "")
    try:
        if key:
            return {"success": True, "data": {key: os.environ.get(key, "")}}
        info = {
            "python_version": sys.version,
            "platform": sys.platform,
            "cwd": os.getcwd(),
            "user": os.environ.get("USER", os.environ.get("USERNAME", "")),
            "path_count": len(os.environ.get("PATH", "").split(os.pathsep)),
            "key_vars": {k: v for k, v in sorted(os.environ.items())
                         if not k.startswith("_") and not k.startswith("SECRET")},
        }
        return {"success": True, "data": info}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Unified entry
# ═════════════════════════════════════════════════════════════════════════════

_EXTENDED_TOOLS: dict[str, callable] = {
    "git_commit": _cmd_git_commit,
    "git_push": _cmd_git_push,
    "git_branch": _cmd_git_branch,
    "web_fetch": _cmd_web_fetch,
    "project_tree": _cmd_project_tree,
    "env_query": _cmd_env_query,
}


def execute_extended_tool(tool_name: str, args: dict, agent_id: str = "") -> dict:
    handler = _EXTENDED_TOOLS.get(tool_name)
    if handler is None:
        return {"success": False, "error": f"unknown extended tool: {tool_name}"}
    try:
        return handler(args, agent_id)
    except Exception as e:
        return {"success": False, "error": str(e)}