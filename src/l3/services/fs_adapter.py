"""FilesystemPort adapter — OS-direct implementation (read/write/tree/watch).

Implements the K-domain FilesystemPort abstraction so L4 API endpoints and
future sandbox/VFS mounts share one interface. Watch uses mtime polling
(no external dependency); the polling thread is per-root and daemonized.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from l1.kernel.params.system import FS_WATCH_INTERVAL, HASH_TRUNC_LONG
from l1.kernel.ports import FilesystemPort

logger = logging.getLogger(__name__)


class FsAdapter(FilesystemPort):
    """Filesystem port adapter — direct OS access with path safety checks."""

    def __init__(self, watch_interval: float = FS_WATCH_INTERVAL):
        self._watch_interval = watch_interval
        self._watchers: dict[str, dict] = {}  # root -> {"mtime": float, "stop": bool}
        self._lock = threading.Lock()

    def read(self, path: str) -> dict:
        """Read a text file (UTF-8); returns content or an error dict."""
        try:
            p = Path(path).resolve()
            if not p.exists():
                return {"success": False, "error": "file not found"}
            if not p.is_file():
                return {"success": False, "error": "not a file"}
            return {"success": True, "content": p.read_text(encoding="utf-8"), "size": p.stat().st_size}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write(self, path: str, content: str) -> dict:
        """Write text content (UTF-8), creating parent dirs; returns size."""
        try:
            p = Path(path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(p), "size": len(content.encode("utf-8"))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_tree(self, root: str) -> dict:
        """Recursively list all entries under root with relative paths."""
        try:
            p = Path(root).resolve()
            if not p.exists():
                return {"success": False, "error": "path not found"}
            if not p.is_dir():
                return {"success": False, "error": "not a directory"}
            entries = []
            for child in sorted(p.rglob("*")):
                try:
                    rel = str(child.relative_to(p))
                    entries.append(
                        {
                            "path": rel.replace("\\", "/"),
                            "type": "dir" if child.is_dir() else "file",
                            "size": child.stat().st_size if child.is_file() else 0,
                        }
                    )
                except OSError:
                    continue
            return {"success": True, "root": str(p), "entries": entries, "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def watch(self, root: str, callback: Callable) -> dict:
        """Start mtime-polling a directory, invoking callback on change."""
        try:
            p = Path(root).resolve()
            if not p.exists():
                return {"success": False, "error": "path not found"}
            with self._lock:
                if root in self._watchers:
                    return {"success": False, "error": f"already watching: {root}"}
                self._watchers[root] = {"mtime": self._snapshot(p), "stop": False, "callback": callback}
            threading.Thread(
                target=self._poll, args=(str(p), root), name=f"fs-watch-{root[:HASH_TRUNC_LONG]}", daemon=True
            ).start()
            return {"success": True, "watching": root}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _snapshot(self, p: Path) -> float:
        latest = p.stat().st_mtime
        try:
            for child in p.rglob("*"):
                try:
                    latest = max(latest, child.stat().st_mtime)
                except OSError:
                    continue
        except OSError:
            pass
        return latest

    def _poll(self, root: str, key: str) -> None:
        while True:
            time.sleep(self._watch_interval)
            with self._lock:
                watcher = self._watchers.get(key)
                if not watcher or watcher["stop"]:
                    return
            try:
                mtime = self._snapshot(Path(root))
                if mtime != watcher["mtime"]:
                    watcher["mtime"] = mtime
                    try:
                        watcher["callback"]({"root": root, "changed_at": time.time()})
                    except Exception as e:
                        logger.debug("fs watch callback failed: %s", e)
            except OSError:
                continue

    def unwatch(self, root: str) -> dict:
        """Stop watching a root directory."""
        with self._lock:
            watcher = self._watchers.get(root)
            if not watcher:
                return {"success": False, "error": f"not watching: {root}"}
            watcher["stop"] = True
            self._watchers.pop(root, None)
        return {"success": True}


_adapter: FsAdapter | None = None
_adapter_lock = threading.Lock()


def get_adapter() -> FsAdapter:
    """Get the FsAdapter singleton (self-registers on the fs port)."""
    global _adapter
    if _adapter is None:
        with _adapter_lock:
            if _adapter is None:
                watch_interval = FS_WATCH_INTERVAL
                try:
                    from l3.config.settings_center import get_center as _sc

                    watch_interval = float(_sc().get("fs.watch_interval", FS_WATCH_INTERVAL))
                except Exception:
                    pass
                _adapter = FsAdapter(watch_interval=watch_interval)
                try:
                    from l1.kernel.ports import register_port

                    register_port("fs", _adapter)
                except Exception:
                    logger.debug("fs: port self-registration skipped")
    return _adapter


def reset_adapter() -> None:
    """Stop watchers and drop the singleton (testing)."""
    global _adapter
    if _adapter:
        with _adapter._lock:
            for w in _adapter._watchers.values():
                w["stop"] = True
            _adapter._watchers.clear()
    _adapter = None
