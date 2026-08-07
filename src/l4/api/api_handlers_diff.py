"""API handlers for structured diff queries — exposes sandbox diff data to frontends.

Gated by ``diff_heavy_api_enabled`` setting (default False).
"""

from __future__ import annotations

import logging

from l1.kernel.params.system import PAGER_RECALL_LIMIT

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    """Check whether the heavy diff API is enabled.

    Precedence: env var > config file > disabled by default.
    """
    import os

    env = os.environ.get("PRAXIS_DIFF_HEAVY_API", "").lower()
    if env in ("1", "true", "yes"):
        return True
    try:
        from l3.config.settings_center import get_center

        return bool(get_center().get("diff.heavy_api_enabled", False))
    except Exception:
        return False


def diff_structured(body: dict) -> dict:
    """POST /api/diff/structured — Get structured diff for a sandbox-staged file.

    Request body::

        {"path": "src/foo.py",          # required
         "mode": "agent"|"human"|"summary",  # optional, default "agent"
         "cell_id": "cell-1"}           # optional, searches all cells if omitted

    Returns:
      agent mode   → raw hunks (full structure, for LLM)
      human mode   → unified diff text
      summary mode → lightweight structured summary (for dashboard, cached)
    """
    if not _is_enabled():
        return {"success": False, "error": "diff heavy API is disabled (set diff.heavy_api_enabled=true)"}
    path = body.get("path", "")
    if not path:
        return {"success": False, "error": "path required"}
    mode = body.get("mode", "agent")
    if mode not in ("agent", "human", "summary", "colored"):
        return {"success": False, "error": f"invalid mode: {mode!r}"}
    cell_id = body.get("cell_id", "")

    try:
        from l4.sandbox import get_manager as _get_sb

        sb_mgr = _get_sb()
    except Exception as e:
        return {"success": False, "error": f"sandbox unavailable: {e}"}

    found_cell: str = ""
    result = None

    if cell_id:
        sb = sb_mgr.get_cell(cell_id)
        if sb:
            if mode == "summary":
                result = sb.get_entry_summary(path)
            else:
                entry = sb.get_entry(path)
                if entry:
                    result = entry.hunks if mode == "agent" else entry.to_human_readable()
            if result:
                found_cell = cell_id
    else:
        try:
            status = sb_mgr.status()
            for cid in status:
                sb = sb_mgr.get_cell(cid)
                if not sb:
                    continue
                if mode == "summary":
                    result = sb.get_entry_summary(path)
                else:
                    entry = sb.get_entry(path)
                    if entry:
                        result = entry.hunks if mode == "agent" else entry.to_human_readable()
                if result:
                    found_cell = cid
                    break
        except Exception:
            logger.debug("api_handlers_diff: cell scan in diff_structured failed")

    if not result:
        return {"success": False, "error": f"no sandbox entry for {path}"}

    if mode == "summary":
        return {
            "success": True,
            "path": path,
            "cell_id": found_cell,
            "summary": result,
        }

    # colored mode uses to_colored_diff() instead of raw hunks
    if mode == "colored":
        colored = entry.to_colored_diff()
        return {
            "success": True,
            "path": path,
            "cell_id": found_cell,
            "colored_diff": colored,
        }

    return {
        "success": True,
        "path": path,
        "cell_id": found_cell,
        "agent_id": entry.agent_id,
        "task_id": entry.task_id,
        "status": entry.status,
        "conflict_level": entry.conflict_level,
        "stats": entry.stats,
        "modified_at": entry.modified_at,
        "hunks": result if mode == "agent" else None,
        "human_readable": result if mode == "human" else None,
    }


def diff_history(body: dict) -> dict:
    """GET /api/diff/history — List all sandbox entries across cells.

    Request body::

        {"cell_id": "cell-1",           # optional, filter by cell
         "agent_id": "agent-a",         # optional, filter by agent
         "path": "src/foo.py",          # optional, filter by path
         "limit": 20}                   # optional, default 50
    """
    if not _is_enabled():
        return {"success": False, "error": "diff heavy API is disabled (set diff.heavy_api_enabled=true)"}
    cell_id = body.get("cell_id", "")
    agent_id = body.get("agent_id", "")
    path_filter = body.get("path", "")
    limit = body.get("limit", PAGER_RECALL_LIMIT)

    try:
        from l4.sandbox import get_manager as _get_sb

        sb_mgr = _get_sb()
    except Exception as e:
        return {"success": False, "error": f"sandbox unavailable: {e}"}

    entries: list[dict] = []
    try:
        status = sb_mgr.status()
        cells = [cell_id] if cell_id else list(status.keys())
        for cid in cells:
            sb = sb_mgr.get_cell(cid)
            if not sb:
                continue
            for entry in sb.get_entries():
                if path_filter and entry.path != path_filter:
                    continue
                if agent_id and entry.agent_id != agent_id:
                    continue
                if entry.status in ("flushed", "discarded"):
                    continue
                entries.append(
                    {
                        "path": entry.path,
                        "cell_id": cid,
                        "agent_id": entry.agent_id,
                        "tool_name": entry.tool_name,
                        "status": entry.status,
                        "task_id": entry.task_id,
                        "conflict_level": entry.conflict_level,
                        "stats": entry.stats,
                        "modified_at": entry.modified_at,
                    }
                )
                if len(entries) >= limit:
                    break
            if len(entries) >= limit:
                break
    except Exception:
        logger.debug("api_handlers_diff: cell scan in diff_history failed")

    return {"success": True, "entries": entries, "count": len(entries)}


def diff_colors(body: dict | None = None) -> dict:
    """GET /api/diff/colors — Get current color scheme.

    POST /api/diff/colors — Update color scheme.

    Request body (POST)::

        {"scheme": {"logic_change": "\\\\033[31m", ...}}

    All semantic keys are optional; only provided keys are updated.
    """
    from l4.sandbox.cell_sandbox import get_color_scheme, reset_color_scheme, set_color_scheme

    b = body or {}
    action = b.get("action", "get")
    if action == "get":
        return {"success": True, "scheme": get_color_scheme()}
    if action == "reset":
        reset_color_scheme()
        return {"success": True, "scheme": get_color_scheme(), "notice": "reset to defaults"}
    scheme = b.get("scheme", {})
    if not isinstance(scheme, dict):
        return {"success": False, "error": "scheme must be a dict"}
    set_color_scheme(scheme)
    return {"success": True, "scheme": get_color_scheme(), "updated": list(scheme.keys())}
