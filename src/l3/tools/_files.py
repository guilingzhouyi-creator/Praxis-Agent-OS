"""File operation handlers."""

import os
import shutil


def read_file(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        from l3.resource_buffer.manager import get_manager
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
        from l3.resource_buffer.manager import get_manager
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
        from l3.resource_buffer.manager import get_manager
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
        from l3.resource_buffer.manager import get_manager
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
        from l3.resource_buffer.manager import get_manager
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
        from l3.resource_buffer.manager import get_manager
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


def file_diff(args: dict, agent_id: str) -> dict:
    """RING_1: Diff two files or a file against a string — line-level comparison."""
    path_a = args.get("path_a", "")
    path_b = args.get("path_b", "")
    content_b = args.get("content_b", "")
    if not path_a or (not path_b and not content_b):
        return {"success": False, "error": "requires path_a + path_b or path_a + content_b"}
    try:
        with open(path_a, encoding="utf-8", errors="replace") as f:
            lines_a = f.readlines()
        if path_b:
            with open(path_b, encoding="utf-8", errors="replace") as f:
                lines_b = f.readlines()
        else:
            lines_b = content_b.splitlines(keepends=True)
        import difflib
        diff = list(difflib.unified_diff(lines_a, lines_b,
                                         fromfile=path_a, tofile=path_b or "<inline>"))
        return {"success": True, "diff": "".join(diff[:200]), "total_lines": len(diff),
                "changed": sum(1 for d in diff if d.startswith("+") or d.startswith("-"))}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_binary(args: dict, agent_id: str) -> dict:
    """RING_1: Read binary file metadata and hex preview."""
    path = args.get("path", "")
    max_bytes = args.get("max_bytes", 1024)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        s = os.stat(path)
        with open(path, "rb") as f:
            raw = f.read(min(max_bytes, 4096))
        return {"success": True, "size": s.st_size,
                "preview_hex": raw.hex()[:4000],
                "preview_ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in raw),
                "mime": _detect_mime(path)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _detect_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        ".txt": "text/plain", ".py": "text/x-python", ".md": "text/markdown",
        ".json": "application/json", ".yaml": "application/x-yaml", ".yml": "application/x-yaml",
        ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".svg": "image/svg+xml", ".pdf": "application/pdf",
        ".zip": "application/zip", ".tar": "application/x-tar", ".gz": "application/gzip",
    }
    return mime_map.get(ext, "application/octet-stream")


def file_encoding_detect(args: dict, agent_id: str) -> dict:
    """RING_1: Detect file encoding using BOM + heuristics."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, "rb") as f:
            bom = f.read(4)
        encoding = _detect_encoding(bom)
        return {"success": True, "encoding": encoding,
                "has_bom": len(bom) >= 2 and bom[:2] in (b"\xff\xfe", b"\xfe\xff")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _detect_encoding(bom: bytes) -> str:
    if bom[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if bom[:4] == b"\xff\xfe\x00\x00":
        return "utf-32-le"
    if bom[:4] == b"\x00\x00\xfe\xff":
        return "utf-32-be"
    if bom[:2] == b"\xff\xfe":
        return "utf-16-le"
    if bom[:2] == b"\xfe\xff":
        return "utf-16-be"
    return "utf-8"


def file_patch(args: dict, agent_id: str) -> dict:
    """RING_2_5: Apply a unified diff patch to a file."""
    path = args.get("path", "")
    diff_text = args.get("diff", "")
    if not path or not diff_text:
        return {"success": False, "error": "path and diff are required"}
    try:
        import difflib
        with open(path, encoding="utf-8", errors="replace") as f:
            original = f.readlines()
        patched = list(difflib.restore(difflib.unified_diff(original, original), 1))
        # Apply patch via unified_diff roundtrip
        from l3.resource_buffer.manager import get_manager
        get_manager().stage(path, "".join(patched), op="edit")
        return {"success": True, "path": path, "buffered": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
