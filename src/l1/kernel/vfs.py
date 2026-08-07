"""Virtual File System — kernel-level file abstraction.

All file operations in the Agent OS go through VFS, which provides:
  - Mount table (project root, sandbox, temp, virtual paths)
  - Access control (ring-level permissions on mount points)
  - Unified read/write/stat/list interface
  - File content cache integration

No tool or service reads/writes directly to the OS filesystem.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from .params.kernel import VFS_DEFAULT_MIN_RING, VFS_PROC_PATH
from .params.system import FILE_CACHE_TTL

logger = logging.getLogger(__name__)


class MountType(Enum):
    """MountType — enum of PROJECT, SANDBOX, TEMP, VIRTUAL...."""

    PROJECT = auto()  # real project directory
    SANDBOX = auto()  # sandbox directory (COW)
    TEMP = auto()  # temporary directory
    VIRTUAL = auto()  # in-memory virtual files
    SYSTEM = auto()  # kernel system files (/proc, /sys equivalents)


@dataclass
class MountPoint:
    """MountPoint — mount point record (name, mount_type, real_path, min_ring, read_only)."""

    name: str
    mount_type: MountType
    real_path: str = ""
    min_ring: int = VFS_DEFAULT_MIN_RING
    read_only: bool = False
    description: str = ""


@dataclass
class VNode:
    """Virtual inode — represents a file in VFS."""

    path: str
    size: int = 0
    is_dir: bool = False
    mode: str = "r--"
    mount: str = ""
    created_at: float = field(default_factory=time.time)
    modified_at: float = field(default_factory=time.time)


class VFS:
    """Virtual File System — kernel-level file operations.

    Mount table:
      /project  → real project directory (Ring 1 read, Ring 2.5 write)
      /sandbox  → sandbox directory (Ring 1 read, Ring 2.5 write)
      /tmp      → temp directory (all rings)
      /proc     → kernel process table (Ring 1 read-only)
    """

    def __init__(self):
        self._mounts: dict[str, MountPoint] = {}
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[str, float]] = {}  # path → (content, expires_at)
        self._virtual_files: dict[str, str] = {}
        # Pre-sorted prefix list (longest-first) for O(1) _resolve.
        self._sorted_prefixes: list[str] = []

    def mount(
        self,
        name: str,
        mount_type: MountType,
        real_path: str = "",
        min_ring: int = VFS_DEFAULT_MIN_RING,
        read_only: bool = False,
        description: str = "",
    ) -> dict:
        """Mount a filesystem at the given name prefix."""
        with self._lock:
            if name in self._mounts:
                return {"success": False, "error": f"mount point '{name}' already exists"}
            self._mounts[name] = MountPoint(
                name=name,
                mount_type=mount_type,
                real_path=real_path,
                min_ring=min_ring,
                read_only=read_only,
                description=description,
            )
            # Rebuild sorted cache: longest prefix first, so _resolve matches
            # the most specific mount point without runtime sorting.
            self._sorted_prefixes = sorted(self._mounts, key=lambda p: -len(p))
            return {"success": True, "mount": name, "real_path": real_path}

    def _resolve(self, path: str) -> tuple[MountPoint | None, str, str]:
        """Resolve a VFS path to (mount, relative_path, real_path).

        Uses self._sorted_prefixes (longest-first) instead of sorting on each call.
        Returns (None, _, _) if no mount matches.
        """
        for prefix in self._sorted_prefixes:
            mp = self._mounts.get(prefix)
            if mp is None:
                continue  # stale entry from dynamic unmount; skip
            if path == prefix or path.startswith(prefix + "/"):
                rel = path[len(prefix) :].lstrip("/")
                real = os.path.join(mp.real_path, rel) if mp.real_path else ""
                return mp, rel, real
        return None, "", ""

    def read(self, path: str, agent_ring: int = VFS_DEFAULT_MIN_RING) -> dict:
        """Read a file through VFS. Checks mount permissions."""
        # Kernel virtual filesystems — dynamic content
        if path.startswith("/proc"):
            return self.proc_read(path)
        if path.startswith("/sys"):
            return self.sys_read(path)
        if path.startswith("/skills"):
            return self.skill_read(path)
        if path.startswith("/dev"):
            return self.dev_read(path)

        mp, rel, real = self._resolve(path)
        if not mp:
            return {"success": False, "error": f"ENOENT: no mount for '{path}'", "error_code": "ENOENT"}
        if agent_ring < mp.min_ring:
            return {"success": False, "error": "EACCES: ring too low", "error_code": "EACCES"}

        # Check cache first
        now = time.time()
        with self._lock:
            cached = self._cache.get(path)
            if cached and now < cached[1]:
                return {"success": True, "content": cached[0], "cached": True}

        # Virtual file
        if mp.mount_type == MountType.VIRTUAL:
            with self._lock:
                content = self._virtual_files.get(path, "")
            return {"success": True, "content": content, "mount": mp.name}

        # Real file
        try:
            with open(real, encoding="utf-8", errors="replace") as f:
                content = f.read()
            with self._lock:
                self._cache[path] = (content, time.time() + FILE_CACHE_TTL)
            return {"success": True, "content": content, "mount": mp.name, "cached": False}
        except FileNotFoundError:
            return {"success": False, "error": f"ENOENT: {real}", "error_code": "ENOENT"}
        except Exception as e:
            return {"success": False, "error": f"EIO: {e}", "error_code": "EIO"}

    def write(self, path: str, content: str, agent_ring: int = VFS_DEFAULT_MIN_RING) -> dict:
        """Write a file through VFS. Checks mount permissions."""
        mp, rel, real = self._resolve(path)
        if not mp:
            return {"success": False, "error": f"ENOENT: no mount for '{path}'", "error_code": "ENOENT"}
        if agent_ring < mp.min_ring:
            return {"success": False, "error": "EACCES: ring too low", "error_code": "EACCES"}
        if mp.read_only:
            return {"success": False, "error": "EROFS: read-only mount", "error_code": "EROFS"}

        # Invalidate cache
        with self._lock:
            self._cache.pop(path, None)

        if mp.mount_type == MountType.VIRTUAL:
            with self._lock:
                self._virtual_files[path] = content
            return {"success": True, "mount": mp.name, "path": path}

        try:
            Path(real).parent.mkdir(parents=True, exist_ok=True)
            with open(real, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "mount": mp.name, "path": real}
        except Exception as e:
            return {"success": False, "error": f"EIO: {e}", "error_code": "EIO"}

    def list_dir(self, path: str, agent_ring: int = VFS_DEFAULT_MIN_RING) -> dict:
        """List directory contents through VFS."""
        mp, rel, real = self._resolve(path)
        if not mp:
            return {"success": False, "error": f"ENOENT: no mount for '{path}'", "error_code": "ENOENT"}
        if agent_ring < mp.min_ring:
            return {"success": False, "error": "EACCES: ring too low", "error_code": "EACCES"}

        if mp.mount_type == MountType.VIRTUAL:
            with self._lock:
                entries = [k for k in self._virtual_files if k.startswith(path)]
            return {"success": True, "entries": entries, "mount": mp.name}

        try:
            entries = sorted(os.listdir(real))
            return {"success": True, "entries": entries, "mount": mp.name}
        except FileNotFoundError:
            return {"success": False, "error": f"ENOENT: {real}", "error_code": "ENOENT"}
        except Exception as e:
            return {"success": False, "error": f"EIO: {e}", "error_code": "EIO"}

    def invalidate_cache(self, path: str) -> None:
        """Drop cached entries for *path* and everything beneath it."""
        with self._lock:
            self._cache.pop(path, None)
            for k in list(self._cache):
                if k.startswith(path):
                    self._cache.pop(k, None)

    def mounts(self) -> list[dict]:
        """List all registered mounts as dicts."""
        with self._lock:
            return [
                {
                    "name": m.name,
                    "type": m.mount_type.name,
                    "real_path": m.real_path,
                    "min_ring": m.min_ring,
                    "read_only": m.read_only,
                    "description": m.description,
                }
                for m in self._mounts.values()
            ]

    @property
    def proc_path(self) -> str:
        return VFS_PROC_PATH

    def unmount(self, name: str) -> dict:
        """Unmount a filesystem by name prefix."""
        with self._lock:
            if name not in self._mounts:
                return {"success": False, "error": f"mount point '{name}' not found"}
            del self._mounts[name]
            self._sorted_prefixes = sorted(self._mounts, key=lambda p: -len(p))
            # Drop cached entries under this mount
            for k in list(self._cache):
                if k == name or k.startswith(name + "/"):
                    self._cache.pop(k, None)
            return {"success": True, "unmounted": name}

    def sys_read(self, path: str) -> dict:
        """Read /sys files — system registry."""
        from .params.system import KERNEL_VERSION
        from .registry import get_registry
        from .settings import get_settings

        r = get_registry()
        parts = path.strip("/").split("/")
        if len(parts) == 1:
            s = r.summary()
            content = "System Summary\n" + "=" * 40 + "\n"
            for k, v in s.items():
                content += f"{k}: {v}\n"
            return {"success": True, "content": content}
        if "version" in parts:
            return {"success": True, "content": f"Praxis {KERNEL_VERSION}\n"}
        if "modules" in parts:
            m = r.modules()
            content = "Kernel Modules\n" + "=" * 40 + "\n"
            for name, info in m.items():
                content += f"{name:20s} {info.get('status', '?'):>4s}  {info.get('elapsed_ms', 0)}ms\n"
            return {"success": True, "content": content}
        if "settings" in parts:
            s = get_settings().all()
            content = "System Settings\n" + "=" * 40 + "\n"
            for k, v in sorted(s.items()):
                content += f"{k:35s} = {v}\n"
            return {"success": True, "content": content}
        if "syscalls" in parts:
            sc = r.syscalls()
            content = "Registered Syscalls\n" + "=" * 40 + "\n"
            for sc_name in sc:
                content += f"  {sc_name}\n"
            return {"success": True, "content": content}
        return {"success": False, "error": "ENOENT", "error_code": "ENOENT"}

    def skill_read(self, path: str) -> dict:
        """Read /skills files — agent skills."""
        from .skill import get_skill_manager

        sm = get_skill_manager()
        parts = path.strip("/").split("/")
        if len(parts) == 1:
            return {"success": True, "content": sm.skill_vfs_content()}
        if len(parts) >= 2:
            skill_name = parts[1]
            skill = sm.get(skill_name)
            if not skill:
                return {"success": False, "error": "ENOENT: skill not found", "error_code": "ENOENT"}
            if len(parts) == 2:
                # /skills/<name> — list rules
                rules = skill.get("rules", [])
                content = f"Skill: {skill_name}\n"
                content += f"Description: {skill.get('description', '')}\n"
                content += f"Rules ({len(rules)}):\n"
                for r in rules:
                    content += f"  - {r}\n"
                return {"success": True, "content": content}
        return {"success": False, "error": "ENOENT", "error_code": "ENOENT"}

    def dev_read(self, path: str) -> dict:
        """Read /dev files — device manager."""
        from .device import get_device_manager

        dm = get_device_manager()
        parts = path.strip("/").split("/")
        if len(parts) == 1:
            devices = dm.list()
            content = "Devices\n" + "=" * 40 + "\n"
            for d in devices:
                content += (
                    f"{d['name']:15s} {d['type']:12s} {d['health']:10s}  rate={d['rate_limit']} calls={d['calls']}\n"
                )
            return {"success": True, "content": content}
        return {"success": False, "error": "ENOENT", "error_code": "ENOENT"}

    def proc_read(self, path: str) -> dict:
        """Read /proc files (kernel virtual filesystem)."""
        from .process import get_table

        parts = path.strip("/").split("/")
        if len(parts) == 1 and parts[0] == "proc":
            table = get_table()
            procs = table.list_processes()
            content = "PID\tNAME\tROLE\tSTATE\tRING\tUPTIME\n" + "\n".join(
                f"{p['pid']}\t{p['name']}\t{p['role']}\t{p['state']}\t{p['ring']}\t{p['uptime']}s" for p in procs
            )
            return {"success": True, "content": content}
        if len(parts) == 2 and parts[0] == "proc":
            if parts[1] == "mounts":
                mounts = self.mounts()
                content = "Mounts\n" + "=" * 40 + "\n"
                for m in mounts:
                    content += f"{m['name']:15s} {m['type']:10s} ring={m['min_ring']} ro={m['read_only']}\n"
                return {"success": True, "content": content}
            if parts[1] == "processes":
                table = get_table()
                procs = table.list_processes()
                content = "PID\tNAME\tROLE\tSTATE\tRING\tUPTIME\n" + "\n".join(
                    f"{p['pid']}\t{p['name']}\t{p['role']}\t{p['state']}\t{p['ring']}\t{p['uptime']}s" for p in procs
                )
                return {"success": True, "content": content}
            try:
                pid = int(parts[1])
            except ValueError:
                return {"success": False, "error": "ENOENT", "error_code": "ENOENT"}
            table = get_table()
            pcb = table.get(pid)
            if pcb:
                s = pcb.snapshot()
                content = "\n".join(f"{k}: {v}" for k, v in s.items())
                return {"success": True, "content": content}
            return {"success": False, "error": f"ENOENT: no process {pid}", "error_code": "ENOENT"}
        return {"success": False, "error": "ENOENT", "error_code": "ENOENT"}


_vfs: VFS | None = None
_vfs_lock = threading.Lock()


def get_vfs() -> VFS:
    """Get the VFS singleton (lazily created)."""
    global _vfs
    if _vfs is None:
        with _vfs_lock:
            if _vfs is None:
                _vfs = VFS()
    return _vfs


def reset_vfs() -> None:
    """Reset the VFS singleton to None (for tests / hot reset)."""
    global _vfs
    _vfs = None
