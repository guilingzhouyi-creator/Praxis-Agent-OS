"""DEPRECATED — SubAgentFramework has been replaced by SubAgentPool.

See src/l3/agent/subagent_pool.py (SubAgentPool).  This module is
kept for backward compatibility with existing tests.

Architecture (original, now deprecated):
  SubAgentFramework (services/subagent_framework.py)
  ├── SubAgentSpec         — Sub-agent definition (role/tool set/model/timeout)
  ├── SubAgentTask         — Sub-agent task instance (independent session + context)
  ├── SubAgentDispatcher   — @mention parsing + task scheduling + lifecycle
  ├── ResultMerger         — Multi sub-agent result conflict detection + merging
  └── API Handlers

API (still active for backward compat):
  POST /api/subagent/dispatch       — Dispatch subagent
  GET  /api/subagent/:id/result     — Get subagent result
  DELETE /api/subagent/:id          — Cancel subagent
  GET  /api/subagent/specs          — List subagent specs
  POST /api/subagent/spec           — Register subagent spec
"""

from __future__ import annotations

import logging
import threading

from .subagent_dispatcher import SubAgentDispatcher
from .subagent_merger import ResultMerger
from .subagent_spec import SubAgentSpec

logger = logging.getLogger(__name__)

_dispatcher: SubAgentDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_dispatcher() -> SubAgentDispatcher:
    global _dispatcher
    if _dispatcher is None:
        with _dispatcher_lock:
            if _dispatcher is None:
                _dispatcher = SubAgentDispatcher()
    return _dispatcher


# ══════════════════════════════════════════════════════════════════════
# 6. API Handlers
# ══════════════════════════════════════════════════════════════════════


def handle_subagent_dispatch(body: dict | None = None,
                              cell=None) -> dict:
    """POST /api/subagent/dispatch — Dispatch subagent"""
    b = body or {}
    spec_name = b.get("spec", "")
    prompt = b.get("prompt", "")
    text = b.get("text", "")
    parent = b.get("parent_agent_id", "")

    if text:
        return get_dispatcher().dispatch_from_text(text, parent, cell=cell)

    if not spec_name or not prompt:
        return {"success": False, "error": "spec+prompt or text required"}
    return get_dispatcher().dispatch(spec_name, prompt, parent, cell=cell)


def handle_subagent_result(body: dict | None = None) -> dict:
    """POST /api/subagent/result — Get subagent result"""
    b = body or {}
    task_id = b.get("task_id", "")
    if not task_id:
        return {"success": False, "error": "task_id required"}
    task = get_dispatcher().get_task(task_id)
    if not task:
        return {"success": False, "error": f"task not found: {task_id}"}
    return task.get_result()


def handle_subagent_cancel(body: dict | None = None) -> dict:
    """POST /api/subagent/cancel — Cancel subagent"""
    b = body or {}
    task_id = b.get("task_id", "")
    if not task_id:
        return {"success": False, "error": "task_id required"}
    return get_dispatcher().cancel_task(task_id)


def handle_subagent_list(body: dict | None = None) -> dict:
    """POST /api/subagent/tasks — List subagent tasks"""
    b = body or {}
    status = b.get("status", "")
    return {"success": True, "tasks": get_dispatcher().list_tasks(status=status)}


def handle_subagent_specs(body: dict | None = None) -> dict:
    """GET /api/subagent/specs — List subagent specs"""
    return get_dispatcher().list_specs()


def handle_subagent_spec_register(body: dict | None = None) -> dict:
    """POST /api/subagent/spec — Register subagent spec"""
    b = body or {}
    name = b.get("name", "")
    desc = b.get("description", "")
    if not name or not desc:
        return {"success": False, "error": "name and description required"}
    spec = SubAgentSpec(
        name=name,
        description=desc,
        system_prompt=b.get("system_prompt", ""),
        allowed_tools=b.get("allowed_tools", ["read_file", "grep_search"]),
        model=b.get("model", ""),
        max_steps=b.get("max_steps", 5),
        timeout=b.get("timeout", 60.0),
        read_only=b.get("read_only", True),
        tags=b.get("tags", []),
    )
    return get_dispatcher().register_spec(spec)


def handle_subagent_merge(body: dict | None = None) -> dict:
    """POST /api/subagent/merge — Merge multiple subagent results"""
    b = body or {}
    task_ids = b.get("task_ids", [])
    if not task_ids:
        return {"success": False, "error": "task_ids required"}

    results = []
    for tid in task_ids:
        task = get_dispatcher().get_task(tid)
        if task:
            results.append(task.get_result())

    return ResultMerger.merge(results)


# ── Route Registration ──
# Routes are consolidated in l4/api/api_endpoints.py (ENDPOINT_MANIFEST); no duplicate list maintained here.
