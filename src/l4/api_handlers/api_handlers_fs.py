"""FS API handlers — file tree/read/watch over the FilesystemPort adapter.

Endpoints:
  GET /api/v2/fs/tree  — list a directory tree
  GET /api/v2/fs/read  — read a file
  POST /api/v2/fs/watch — watch a directory for changes
"""

from __future__ import annotations


def _get_fs():
    from l3.services.fs_adapter import get_adapter

    return get_adapter()


def handle_fs_tree(body: dict | None = None) -> dict:
    """GET /api/v2/fs/tree — list a directory tree."""
    b = body or {}
    root = str(b.get("root") or ".").strip()
    try:
        r = _get_fs().list_tree(root)
    except Exception as e:
        return {"success": False, "error": f"tree failed: {e}"}
    return r


def handle_fs_read(body: dict | None = None) -> dict:
    """GET /api/v2/fs/read — read a file's text content."""
    b = body or {}
    path = str(b.get("path") or "").strip()
    if not path:
        return {"success": False, "error": "path required"}
    try:
        r = _get_fs().read(path)
    except Exception as e:
        return {"success": False, "error": f"read failed: {e}"}
    return r


def handle_fs_watch(body: dict | None = None) -> dict:
    """POST /api/v2/fs/watch — start watching a directory for changes.

    Change events are delivered over SSE/WS as ``fs.changed`` (the watcher
    callback emits through the event bus); the API call only registers the
    watch and returns the root.
    """
    b = body or {}
    root = str(b.get("root") or "").strip()
    if not root:
        return {"success": False, "error": "root required"}

    def _on_change(info: dict) -> None:
        try:
            from l1.kernel import emit_event

            emit_event("fs.changed", info, source="fs_adapter")
        except Exception:
            pass

    try:
        r = _get_fs().watch(root, _on_change)
    except Exception as e:
        return {"success": False, "error": f"watch failed: {e}"}
    return r


def handle_fs_unwatch(body: dict | None = None) -> dict:
    """POST /api/v2/fs/unwatch — stop watching a directory."""
    b = body or {}
    root = str(b.get("root") or "").strip()
    if not root:
        return {"success": False, "error": "root required"}
    try:
        r = _get_fs().unwatch(root)
    except Exception as e:
        return {"success": False, "error": f"unwatch failed: {e}"}
    return r
