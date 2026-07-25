"""Advanced file operation tools - 9 kinds.

file_move, file_copy, file_delete, file_stat, file_mkdir,
file_append, file_insert_lines, file_delete_lines, file_chmod
"""

import os
import shutil
from datetime import datetime, timezone

from constants import ToolRing as R
from services.tool_spec import ParamSpec, tool


@tool(name="file_move", description="Move/rename file or directory", category="generic",
       ring=R.RING_2_5, danger=1,
       params=[ParamSpec("source", "string", required=True), ParamSpec("destination", "string", required=True)])
def _cmd_file_move(args: dict, agent_id: str) -> dict:
    src = args.get("source", "")
    dst = args.get("destination", "")
    if not src or not dst:
        return {"success": False, "error": "source and destination are required"}
    try:
        shutil.move(src, dst)
        return {"success": True, "data": {"from": src, "to": dst}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_copy", description="Copy file or directory", category="generic",
       ring=R.RING_2_5, danger=1,
       params=[ParamSpec("source", "string", required=True), ParamSpec("destination", "string", required=True)])
def _cmd_file_copy(args: dict, agent_id: str) -> dict:
    src = args.get("source", "")
    dst = args.get("destination", "")
    if not src or not dst:
        return {"success": False, "error": "source and destination are required"}
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"success": True, "data": {"from": src, "to": dst}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_delete", description="Delete file or directory (irreversible, requires G4 approval)", category="generic",
       ring=R.RING_2_5, danger=3,
       params=[ParamSpec("path", "string", required=True)])
def _cmd_file_delete(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return {"success": True, "data": {"deleted": path}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_stat", description="Query file metadata (size, permissions, timestamps)", category="generic",
       ring=R.RING_1, danger=0,
       params=[ParamSpec("path", "string", required=True)])
def _cmd_file_stat(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        s = os.stat(path)
        return {
            "success": True,
            "data": {
                "path": path,
                "size": s.st_size,
                "mode": oct(s.st_mode),
                "is_dir": os.path.isdir(path),
                "is_file": os.path.isfile(path),
                "modified": datetime.fromtimestamp(s.st_mtime, tz=timezone.utc).isoformat(),
                "created": datetime.fromtimestamp(s.st_ctime, tz=timezone.utc).isoformat(),
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_mkdir", description="Create directory", category="generic",
       ring=R.RING_2_5, danger=1,
       params=[ParamSpec("path", "string", required=True), ParamSpec("parents", "bool", default=False)])
def _cmd_file_mkdir(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    parents = args.get("parents", False)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        if parents:
            os.makedirs(path, exist_ok=True)
        else:
            os.mkdir(path)
        return {"success": True, "data": {"created": path, "parents": parents}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_append", description="Append content to end of file", category="generic",
       ring=R.RING_2_5, danger=1,
       params=[ParamSpec("path", "string", required=True), ParamSpec("content", "string", default="")])
def _cmd_file_append(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content + ("\n" if not content.endswith("\n") else ""))
        return {"success": True, "data": {"path": path, "appended": len(content) + 1}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_insert_lines", description="Insert content at specified line", category="generic",
       ring=R.RING_2_5, danger=1,
       params=[ParamSpec("path", "string", required=True), ParamSpec("line", "int", default=1), ParamSpec("content", "string", required=True)])
def _cmd_file_insert_lines(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    line = args.get("line", 1)
    content = args.get("content", "")
    if not path or not content:
        return {"success": False, "error": "path and content are required"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        idx = max(0, min(line - 1, len(lines)))
        insert = content.splitlines(keepends=True)
        lines[idx:idx] = insert
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return {"success": True, "data": {"path": path, "at_line": line, "inserted": len(insert)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_delete_lines", description="Delete specified line range", category="generic",
       ring=R.RING_2_5, danger=2,
       params=[ParamSpec("path", "string", required=True), ParamSpec("start_line", "int", default=1), ParamSpec("end_line", "int", default=1)])
def _cmd_file_delete_lines(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    start_line = args.get("start_line", 1)
    end_line = args.get("end_line", start_line)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if start_line < 1 or end_line > len(lines):
            return {"success": False, "error": f"line range {start_line}-{end_line} out of range (1-{len(lines)})"}
        deleted = lines[start_line - 1:end_line]
        lines[start_line - 1:end_line] = []
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return {"success": True, "data": {"path": path, "deleted_lines": len(deleted)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(name="file_chmod", description="Change file permissions", category="generic",
       ring=R.RING_2_5, danger=1,
       params=[ParamSpec("path", "string", required=True), ParamSpec("mode", "string", required=True)])
def _cmd_file_chmod(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    mode = args.get("mode", "")
    if not path or not mode:
        return {"success": False, "error": "path and mode are required"}
    try:
        mode_int = int(str(mode), 8) if isinstance(mode, str) else mode
        os.chmod(path, mode_int)
        return {"success": True, "data": {"path": path, "mode": oct(mode_int)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    """Backward compat: tools are auto-registered via @tool decorators at import time."""
