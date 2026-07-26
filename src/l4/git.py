"""Git service — repository operations via subprocess.

All methods return dicts with at minimum a "success" key.
Runs git commands via subprocess, parses structured output.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from l1.kernel.params.api import GIT_TIMEOUT

logger = logging.getLogger(__name__)


def _git(args: list[str], cwd: str) -> dict[str, Any]:
    try:
        r = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, cwd=cwd,
            timeout=GIT_TIMEOUT,
        )
        if r.returncode != 0:
            return {"success": False, "error": r.stderr.strip() or "git command failed"}
        return {"success": True, "stdout": r.stdout, "stderr": r.stderr}
    except FileNotFoundError:
        return {"success": False, "error": "git not found"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "git command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def status(path: str) -> dict[str, Any]:
    r = _git(["-C", path, "status", "--porcelain", "-b"], path)
    if not r["success"]:
        return r
    lines = r["stdout"].splitlines()
    branch = ""
    changes: list[dict] = []
    for line in lines:
        if line.startswith("##"):
            # ## branch...origin/branch [ahead N] [behind M]
            branch = line.split()[0][2:].split("...")[0]
        elif line.strip():
            # XY filename
            xy = line[:2]
            fname = line[3:]
            changes.append({
                "path": fname,
                "staged": xy[0] != " ",
                "type": _change_type(xy),
            })
    return {"success": True, "branch": branch, "changes": changes, "count": len(changes)}


def _change_type(xy: str) -> str:
    if "M" in xy:
        return "modified"
    if "A" in xy:
        return "added"
    if "D" in xy:
        return "deleted"
    if "R" in xy:
        return "renamed"
    if "?" in xy:
        return "untracked"
    return "unknown"


def diff(path: str, staged: bool = False) -> dict[str, Any]:
    args = ["-C", path, "diff"]
    if staged:
        args.append("--cached")
    args.append("--unified=5")
    r = _git(args, path)
    if not r["success"]:
        return r
    hunks = _parse_diff(r["stdout"])
    return {"success": True, "hunks": hunks, "count": len(hunks)}


def _parse_diff(diff_text: str) -> list[dict]:
    hunks: list[dict] = []
    current: dict | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            current = {"file": "", "old_start": 0, "old_count": 0, "new_start": 0, "new_count": 0, "lines": []}
            hunks.append(current)
        elif line.startswith("+++ b/"):
            if current:
                current["file"] = line[6:]
        elif line.startswith("@@"):
            if current:
                parts = line.split("@@")[1].strip().split()
                old = parts[0][1:].split(",")
                new = parts[1][1:].split(",")
                current["old_start"] = int(old[0])
                current["old_count"] = int(old[1]) if len(old) > 1 else 1
                current["new_start"] = int(new[0])
                current["new_count"] = int(new[1]) if len(new) > 1 else 1
        elif current and line.startswith(("+", "-", " ")):
            current["lines"].append(line)
    return hunks


def commit(path: str, message: str) -> dict[str, Any]:
    a = _git(["-C", path, "add", "-A"], path)
    if not a["success"]:
        return a
    return _git(["-C", path, "commit", "-m", message], path)


def add(path: str, files: list[str]) -> dict[str, Any]:
    return _git(["-C", path, "add", "--"] + files, path)


def log(path: str, max_count: int = 20) -> dict[str, Any]:
    r = _git(["-C", path, "log", f"--max-count={max_count}", "--format=%H||%an||%ai||%s"], path)
    if not r["success"]:
        return r
    commits = []
    for line in r["stdout"].splitlines():
        parts = line.split("||", 3)
        if len(parts) == 4:
            commits.append({"hash": parts[0], "author": parts[1], "date": parts[2], "message": parts[3]})
    return {"success": True, "commits": commits, "count": len(commits)}


def branch(path: str) -> dict[str, Any]:
    r = _git(["-C", path, "branch", "-a"], path)
    if not r["success"]:
        return r
    branches = []
    for line in r["stdout"].splitlines():
        name = line.strip().replace("* ", "").strip()
        branches.append({"name": name, "current": line.strip().startswith("*")})
    return {"success": True, "branches": branches, "count": len(branches)}


def checkout(path: str, branch_name: str) -> dict[str, Any]:
    return _git(["-C", path, "checkout", branch_name], path)


def init(path: str) -> dict[str, Any]:
    return _git(["init", path], path)
