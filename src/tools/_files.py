"""File operation handlers."""

import os
import shutil


def read_file(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        from services.resource_buffer.manager import get_manager
        content = get_manager().read(path)
        return {"success": True, "data": content, "path": path}
    except FileNotFoundError:
        return {"success": False, "error": "file not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_dir(args: dict, agent_id: str) -> dict:
    path = args.get("path", ".")
    try:
        entries = sorted(os.listdir(path))
        items = []
        for e in entries:
            fp = os.path.join(path, e)
            items.append({"name": e, "is_dir": os.path.isdir(fp)})
        return {"success": True, "data": items, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def file_stat(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        s = os.stat(path)
        return {"success": True, "data": {"size": s.st_size, "mode": oct(s.st_mode), "mtime": s.st_mtime, "is_dir": os.path.isdir(path)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_file(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        from services.resource_buffer.manager import get_manager
        r = get_manager().stage(path, content, op="create")
        return {"success": True, "path": path, "buffer": r}
    except Exception as e:
        return {"success": False, "error": str(e)}


def file_append(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        from services.resource_buffer.manager import get_manager
        current = get_manager().read(path)
        get_manager().stage(path, current + content, op="edit")
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def file_move(args: dict, agent_id: str) -> dict:
    src = args.get("source", "")
    dst = args.get("destination", "")
    if not src or not dst:
        return {"success": False, "error": "source and destination are required"}
    try:
        from services.resource_buffer.manager import get_manager
        content = get_manager().read(src)
        get_manager().stage(dst, content, op="create")
        # After commit, the real move will happen; for now buffer only
        return {"success": True, "from": src, "to": dst, "buffered": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def file_copy(args: dict, agent_id: str) -> dict:
    src = args.get("source", "")
    dst = args.get("destination", "")
    if not src or not dst:
        return {"success": False, "error": "source and destination are required"}
    try:
        from services.resource_buffer.manager import get_manager
        content = get_manager().read(src)
        get_manager().stage(dst, content, op="create")
        return {"success": True, "from": src, "to": dst, "buffered": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def file_delete(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        from services.resource_buffer.manager import get_manager
        get_manager().discard(path)
        if not os.path.exists(path):
            return {"success": True, "deleted": path, "buffered": True}
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return {"success": True, "deleted": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def file_mkdir(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    parents = args.get("parents", False)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        if parents:
            os.makedirs(path, exist_ok=True)
        else:
            os.mkdir(path)
        return {"success": True, "created": path}
    except Exception as e:
        return {"success": False, "error": str(e)}
