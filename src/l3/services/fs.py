"""FileSystem service — cross-platform file operations.

All methods return dicts with at minimum a "success" key.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def read(path: str, encoding: str | None = None) -> dict[str, Any]:
    """Read a file with encoding auto-detection; returns content or an error dict."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "error": "file not found"}
        if not p.is_file():
            return {"success": False, "error": "not a file"}
        # Auto-detect encoding
        raw = p.read_bytes()
        enc = encoding or _detect_encoding(raw)
        text = raw.decode(enc)
        return {"success": True, "content": text, "encoding": enc, "size": len(raw)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write(path: str, content: str, encoding: str = "utf-8") -> dict[str, Any]:
    """Write content to a file, creating parent dirs; returns size or an error dict."""
    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return {"success": True, "size": len(content.encode(encoding))}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_dir(path: str) -> dict[str, Any]:
    """List directory entries with type/size/modified info."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "error": "path not found"}
        if not p.is_dir():
            return {"success": False, "error": "not a directory"}
        entries = []
        for child in sorted(p.iterdir()):
            try:
                stat = child.stat()
                entries.append({
                    "name": child.name,
                    "path": str(child),
                    "type": "dir" if child.is_dir() else "file",
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                continue
        return {"success": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tree(path: str, max_depth: int = 5) -> dict[str, Any]:
    """Build a nested tree of a directory up to max_depth."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "error": "path not found"}
        result = _build_tree(p, 0, max_depth)
        return {"success": True, "tree": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _build_tree(p: Path, depth: int, max_depth: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": p.name, "path": str(p), "type": "dir" if p.is_dir() else "file"}
    if p.is_dir() and depth < max_depth:
        children = []
        for child in sorted(p.iterdir()):
            if child.name.startswith("."):
                continue
            children.append(_build_tree(child, depth + 1, max_depth))
        entry["children"] = children
    return entry


def exists(path: str) -> dict[str, Any]:
    """Return whether the path exists."""
    return {"exists": Path(path).exists()}


def delete(path: str) -> dict[str, Any]:
    """Delete a file or empty directory; returns success or an error dict."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "error": "not found"}
        if p.is_dir():
            p.rmdir()
        else:
            p.unlink()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def mkdir(path: str) -> dict[str, Any]:
    """Create a directory (and parents), ignoring existing dirs."""
    try:
        Path(path).resolve().mkdir(parents=True, exist_ok=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def rename(old_path: str, new_path: str) -> dict[str, Any]:
    """Rename or move a file; returns success or an error dict."""
    try:
        Path(old_path).resolve().rename(Path(new_path).resolve())
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def glob(pattern: str, root: str = ".") -> dict[str, Any]:
    """Recursively match files under root against the pattern."""
    try:
        matches = [str(p) for p in Path(root).resolve().rglob(pattern)]
        return {"success": True, "matches": matches, "count": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Encoding detection ─────────────────────────────────────────

def _detect_encoding(raw: bytes) -> str:
    """Detect file encoding (BOM-first, then try UTF-8/GBK)."""
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if raw[:2] == b"\xff\xfe":
        return "utf-16-le"
    if raw[:2] == b"\xfe\xff":
        return "utf-16-be"
    # Try UTF-8 first
    try:
        raw.decode("utf-8")
        return "utf-8"
    except Exception as e:
            logger.warning("services/fs: %s", e)
    # Fallback to system encoding (GBK on Chinese Windows)
    import locale
    try:
        enc = locale.getpreferredencoding()
        raw.decode(enc)
        return enc
    except UnicodeDecodeError:
        return "utf-8"  # last resort


# ── File watching (polling) ─────────────────────────────────────

_watched: dict[str, dict[str, float]] = {}
_watch_lock = threading.Lock()


def watch_start(root: str, interval: float = 2.0) -> dict[str, Any]:
    """Start polling a directory for changes."""
    p = Path(root).resolve()
    if not p.is_dir():
        return {"success": False, "error": "not a directory"}
    with _watch_lock:
        if str(p) in _watched:
            return {"success": True, "note": "already watching"}
        _watched[str(p)] = {str(f): f.stat().st_mtime for f in p.rglob("*") if f.is_file()}
        threading.Thread(target=_watch_poll, args=(str(p), interval), daemon=True).start()
        return {"success": True}


def _watch_poll(root: str, interval: float) -> None:
    while True:
        time.sleep(interval)
        with _watch_lock:
            old = _watched.get(root, {})
            new: dict[str, float] = {}
            for f in Path(root).rglob("*"):
                if f.is_file():
                    new[str(f)] = f.stat().st_mtime
            changes = []
            for fp, mtime in new.items():
                if fp not in old:
                    changes.append({"type": "created", "path": fp})
                elif old[fp] != mtime:
                    changes.append({"type": "modified", "path": fp})
            for fp in old:
                if fp not in new:
                    changes.append({"type": "deleted", "path": fp})
            if changes:
                _watched[root] = new
                logger.info("watch[%s]: %d changes", root, len(changes))
