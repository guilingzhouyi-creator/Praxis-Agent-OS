"""Agent OS generic tools — 14 tool implementations.

Each tool is an independent _cmd_* function, dispatched by execute_tool.
Phase 19 migration: all tools registered in TOOL_REGISTRY (tool_registry_setup.py).
"""

import hashlib
import hmac
import json
import os
import subprocess
from datetime import datetime, timezone

from constants import (
    TOOL_DANGER_LEVEL, DANGER_TO_GATES,
    TOOL_TERMINAL_TIMEOUT, TOOL_GREP_TIMEOUT,
    TOOL_COMPILE_CHECK_TIMEOUT,
)
from kernel.platform import SHELL_PATH

PRAXIS_TOOLS = {
    name: {"danger": level, "gate": DANGER_TO_GATES.get(level, DANGER_TO_GATES[0])}
    for name, level in TOOL_DANGER_LEVEL.items()
}

_SECRET_KEY = os.urandom(32)
_fingerprint_store: dict[str, dict] = {}


def _compute_fp(data: str, prev_fp: str = "") -> str:
    prev = prev_fp or "GENESIS"
    payload = f"{data}:{prev}"
    return hmac.new(_SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()


def compute_tool_fingerprint(tool_name: str, output: str, agent_id: str) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    raw = f"{tool_name}:{agent_id}:{ts}:{output[:128]}"
    fp = _compute_fp(raw)
    _fingerprint_store[fp[:16]] = {
        "tool_name": tool_name, "output": output,
        "agent_id": agent_id, "timestamp": ts,
    }
    return fp[:16]


def read_fingerprint(fp: str) -> dict | None:
    return _fingerprint_store.get(fp)


# ═════════════════════════════════════════════════════════════════════════════
# Ring 1 — Generic read-only tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_read_fingerprint(args: dict, agent_id: str) -> dict:
    fp = args.get("fingerprint", "")
    data = read_fingerprint(fp)
    if data is None:
        return {"success": False, "error": f"fingerprint {fp} not found"}
    return {"success": True, "data": data}


def _cmd_read_file(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        fp = compute_tool_fingerprint("read_file", content[:256], agent_id)
        return {"success": True, "data": content, "fingerprint": fp}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_grep(args: dict, agent_id: str) -> dict:
    try:
        from kernel.platform import grep_cmd
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        cmd = grep_cmd(pattern, path)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_GREP_TIMEOUT)
        results = r.stdout.splitlines()[:50] if r.returncode == 0 else []
        fp = compute_tool_fingerprint("grep_search", json.dumps(results[:5]), agent_id)
        return {"success": True, "data": results, "fingerprint": fp}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_list_dir(args: dict, agent_id: str) -> dict:
    """List directory contents. Returns file name list."""
    path = args.get("path", ".")
    try:
        items = os.listdir(path)
        items.sort(key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))
        return {"success": True, "data": items}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Ring 2.5 — Generic write tools
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_replace(args: dict, agent_id: str) -> dict:
    """Container isolation replacement: sandbox → compile check → flush."""
    import shutil
    import tempfile
    from pathlib import Path
    path = args.get("path", "")
    old = args.get("old_string", "")
    new = args.get("new_string", "")

    _PROJ = Path(__file__).resolve().parents[1]
    _DEFAULT_SB = os.path.join(tempfile.gettempdir(), "nomos-sandbox", agent_id)
    _SANDBOX = Path(os.environ.get("NOMOS_SANDBOX_ROOT", _DEFAULT_SB))

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        count = content.count(old)
        if count == 0:
            return {"success": False, "error": "old_string not found"}
        content = content.replace(old, new)

        # Write to sandbox
        rel = Path(path).resolve().relative_to(_PROJ)
        sandbox_file = _SANDBOX / rel
        sandbox_file.parent.mkdir(parents=True, exist_ok=True)
        sandbox_file.write_text(content, encoding="utf-8")

        # Compile check
        try:
            r = subprocess.run(["python", "-c",
                f"import ast; ast.parse(open({str(sandbox_file)!r}).read()); print('OK')"],
                capture_output=True, text=True, timeout=TOOL_COMPILE_CHECK_TIMEOUT, cwd=str(_PROJ))
            if r.returncode != 0:
                return {"success": False, "error": f"compile: {r.stderr.strip()[-200:]}",
                        "sandbox": str(sandbox_file)}
        except Exception as e:
            return {"success": False, "error": f"compile check: {e}"}

        # Flush to disk
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(sandbox_file), path)

        fp = compute_tool_fingerprint("replace_string_in_file", f"{path}:changed", agent_id)
        return {"success": True, "data": {"replaced": count, "path": path}, "fingerprint": fp}
    except ValueError:
        # Files outside project: flush directly
        with open(path, encoding="utf-8") as f:
            content = f.read()
        count = content.count(old)
        if count == 0:
            return {"success": False, "error": "old_string not found"}
        content = content.replace(old, new)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        fp = compute_tool_fingerprint("replace_string_in_file", f"{path}:changed", agent_id)
        return {"success": True, "data": {"replaced": count, "path": path}, "fingerprint": fp}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_create(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        fp = compute_tool_fingerprint("create_file", f"{path}:{len(content)}b", agent_id)
        return {"success": True, "data": {"path": path, "size": len(content)}, "fingerprint": fp}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_terminal(args: dict, agent_id: str) -> dict:
    command = args.get("command", "")
    try:
        r = subprocess.run(command, shell=True, executable=SHELL_PATH, capture_output=True, text=True, timeout=TOOL_TERMINAL_TIMEOUT)
        output = r.stdout[-2048:] if len(r.stdout) > 2048 else r.stdout
        fp = compute_tool_fingerprint("run_in_terminal", output[:128], agent_id)
        return {"success": r.returncode == 0, "data": output, "fingerprint": fp}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# Ring 3 — Database tools (MVP placeholder)
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_db_select(args: dict, agent_id: str) -> dict:
    return {"success": False, "error": "db_select not implemented in MVP"}


def _cmd_db_insert(args: dict, agent_id: str) -> dict:
    return {"success": False, "error": "db_insert not implemented in MVP"}


def _cmd_db_update(args: dict, agent_id: str) -> dict:
    return {"success": False, "error": "db_update not implemented in MVP"}


def _cmd_db_delete(args: dict, agent_id: str) -> dict:
    return {"success": False, "error": "db_delete not implemented in MVP"}


def _cmd_db_migrate(args: dict, agent_id: str) -> dict:
    return {"success": False, "error": "db_migrate not implemented in MVP"}


def _cmd_deploy(args: dict, agent_id: str) -> dict:
    return {"success": False, "error": "deploy not implemented in MVP"}


def _cmd_user_delete(args: dict, agent_id: str) -> dict:
    return {"success": False, "error": "user_delete not implemented in MVP"}


# ═════════════════════════════════════════════════════════════════════════════
# Backward compat entry — delegates to TOOL_REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

def execute_tool(tool_name: str, args: dict, agent_id: str = "") -> dict:
    """Unified tool execution entry. Delegates to TOOL_REGISTRY for param validation and dispatch.

    Phase 19: all tools executed via ToolSpec with auto param validation and gate routing.
    """
    from services.tool_spec import execute_tool_spec
    return execute_tool_spec(tool_name, args, agent_id)


def flush_sandbox(agent_id: str, file_path: str) -> dict:
    """Flush sandbox changes to the real filesystem.

    Reads from .praxis/sandbox/{agent_id}/{file_path} and copies to {file_path}.
    """
    from pathlib import Path
    import shutil
    _PROJ = Path(__file__).resolve().parents[1]
    sandbox_file = _PROJ / ".praxis" / "sandbox" / agent_id / file_path.lstrip("/\\")
    if not sandbox_file.exists():
        return {"success": False, "error": f"sandbox file not found: {sandbox_file}"}
    try:
        real_path = _PROJ / file_path.lstrip("/\\")
        real_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(sandbox_file), str(real_path))
        return {"success": True, "data": {"sandbox": str(sandbox_file), "flushed_to": str(real_path)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    """Register all legacy generic tools into TOOL_REGISTRY (Phase 19 migration)."""
    from services.tool_spec import ToolSpec, ParamSpec, register, ToolRing as R

    # Ring 1 — Read-only
    register(ToolSpec(name="read_file", description="Read file content", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True)],
                      handler=_cmd_read_file))
    register(ToolSpec(name="grep_search", description="Search text with regex pattern", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("pattern", "string", required=True),
                                  ParamSpec("path", "string", default=".")],
                      handler=_cmd_grep))
    register(ToolSpec(name="list_dir", description="List directory contents", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", default=".")],
                      handler=_cmd_list_dir))
    register(ToolSpec(name="read_fingerprint", description="Read tool call fingerprint", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("fingerprint", "string", required=True)],
                      handler=_cmd_read_fingerprint))
    # Ring 2.5 — Write
    register(ToolSpec(name="replace_string_in_file", description="Replace string in file (sandbox→compile→flush)",
                      category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True),
                                  ParamSpec("old_string", "string", required=True),
                                  ParamSpec("new_string", "string", required=True)],
                      handler=_cmd_replace))
    register(ToolSpec(name="create_file", description="Create a new file with content", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True),
                                  ParamSpec("content", "string", default="")],
                      handler=_cmd_create))
    register(ToolSpec(name="run_in_terminal", description="Run a command in terminal", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("command", "string", required=True)],
                      handler=_cmd_terminal))
    # Ring 3 — Database (MVP stubs)
    register(ToolSpec(name="db_select", description="Select from database (MVP stub)", category="generic",
                      ring=R.RING_3, danger=3,
                      parameters=[ParamSpec("query", "string", required=True)],
                      handler=_cmd_db_select))
    register(ToolSpec(name="db_insert", description="Insert into database (MVP stub)", category="generic",
                      ring=R.RING_3, danger=3,
                      parameters=[ParamSpec("table", "string", required=True),
                                  ParamSpec("data", "dict", required=True)],
                      handler=_cmd_db_insert))
    register(ToolSpec(name="db_update", description="Update database (MVP stub)", category="generic",
                      ring=R.RING_3, danger=3,
                      parameters=[ParamSpec("table", "string", required=True),
                                  ParamSpec("data", "dict", required=True),
                                  ParamSpec("where", "string", default="")],
                      handler=_cmd_db_update))
    register(ToolSpec(name="db_delete", description="Delete from database (MVP stub)", category="generic",
                      ring=R.RING_3, danger=3,
                      parameters=[ParamSpec("table", "string", required=True),
                                  ParamSpec("where", "string", default="")],
                      handler=_cmd_db_delete))
    register(ToolSpec(name="db_migrate", description="Run database migration (MVP stub)", category="generic",
                      ring=R.RING_3, danger=3,
                      parameters=[ParamSpec("name", "string", required=True)],
                      handler=_cmd_db_migrate))
    register(ToolSpec(name="deploy", description="Deploy project (MVP stub)", category="generic",
                      ring=R.RING_3, danger=3,
                      parameters=[ParamSpec("target", "string", required=True)],
                      handler=_cmd_deploy))
    register(ToolSpec(name="user_delete", description="Delete user (MVP stub)", category="generic",
                      ring=R.RING_3, danger=3,
                      parameters=[ParamSpec("user_id", "string", required=True)],
                      handler=_cmd_user_delete))