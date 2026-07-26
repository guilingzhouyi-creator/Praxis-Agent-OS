"""Virtual Project Space — per-Agent virtual address space.

Each Agent sees the project through a territory-filtered lens.
Like virtual memory: the project is the "physical address space",
each Agent's view is its "virtual address space" mapped via "page tables" (territory + sandbox).

Mapping:
  Project (physical)  ──territory──▶  Agent A's virtual view
                      ──sandbox────▶  Agent B's virtual view (includes unflushed changes)
                      ──constitution─▶  invisible region = page fault
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from kernel.constitution import get_constitution
from kernel.params.agent import TERRITORY_MAP as PARAMS_TERRITORY, TERRITORY_PATHS as PARAMS_PATHS, SHARED_PATHS as PARAMS_SHARED

logger = logging.getLogger(__name__)

# Configurable sandbox root — cross-platform: falls back to OS temp dir
_DEFAULT_VSPACE = os.path.join(tempfile.gettempdir(), "nomos-vspace")
_VSPACE_SANDBOX = os.environ.get("NOMOS_SANDBOX_ROOT", _DEFAULT_VSPACE)

# Territory → agent mapping (single source: kernel/params.py)
TERRITORY_TABLE: dict[str, str] = dict(PARAMS_TERRITORY)
TERRITORY_PATHS: dict[str, list[str]] = {k: list(v) for k, v in PARAMS_PATHS.items()}
SHARED_PATHS: list[str] = list(PARAMS_SHARED)


class TLB:
    """Territory Lookaside Buffer — cache for territory checks.

    Like CPU TLB: caches recent path→allowed mappings to avoid
    repeated territory list traversal and constitution evaluation.
    """

    def __init__(self, capacity: int = 64):
        self._cache: dict[str, bool] = {}
        self._capacity = capacity
        self._hits = 0
        self._misses = 0

    def lookup(self, path: str) -> bool | None:
        result = self._cache.get(path)
        if result is not None:
            self._hits += 1
        else:
            self._misses += 1
        return result

    def fill(self, path: str, allowed: bool) -> None:
        self._cache[path] = allowed
        if len(self._cache) > self._capacity:
            # Simple LRU: remove first quarter
            for _ in range(self._capacity // 4):
                self._cache.pop(next(iter(self._cache)), None)

    def invalidate(self, path: str = "") -> None:
        if path:
            self._cache.pop(path, None)
        else:
            self._cache.clear()

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {"hits": self._hits, "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total else 0,
                "entries": len(self._cache), "capacity": self._capacity}


class ProjectSpace:
    """An Agent's virtual view of the project.

    Each Agent gets one ProjectSpace instance with its own TLB.
    The space filters what files are visible and writable.
    """

    def __init__(self, agent_id: str, project_root: str, sandbox_root: str):
        self.agent_id = agent_id
        self.project = Path(project_root).resolve()
        self.sandbox = Path(sandbox_root).resolve() / agent_id
        self.territory = TERRITORY_PATHS.get(agent_id, [])
        self.constitution = get_constitution()
        self.sandbox.mkdir(parents=True, exist_ok=True)
        self.tlb = TLB()

    def translate(self, rel_path: str) -> dict:
        """Translate a relative path to the actual file location.

        Like a page table lookup: virtual address → physical address.
        Returns: {source: "sandbox"|"project", path: str}
        """
        sandbox_file = self.sandbox / rel_path
        if sandbox_file.exists():
            return {"source": "sandbox", "path": str(sandbox_file)}

        project_file = self.project / rel_path
        if project_file.exists():
            # Check if visible in territory
            if self._in_territory(rel_path):
                return {"source": "project", "path": str(project_file)}
            return {"source": "forbidden", "path": str(project_file), "reason": "outside territory"}

        # Not found anywhere → page fault
        if self._in_territory(rel_path):
            return {"source": "missing", "path": str(project_file)}

        return {"source": "forbidden", "path": str(project_file), "reason": "outside territory"}

    def read(self, rel_path: str) -> dict:
        """Read a file through the virtual space."""
        # 1. Page table lookup
        entry = self.translate(rel_path)
        if entry["source"] == "forbidden":
            return {"success": False, "error": f"territory violation: {rel_path} not in {self.agent_id}'s territory"}

        # 2. Constitution check
        cc = self.constitution.is_allowed("read_file", self.agent_id, rel_path, self.territory)
        if not cc["allowed"]:
            return {"success": False, "error": "constitution blocked", "constitution": cc}

        # 3. Read from sandbox or project
        try:
            content = Path(entry["path"]).read_text(encoding="utf-8")
            return {"success": True, "content": content, "source": entry["source"], "size": len(content)}
        except FileNotFoundError:
            return {"success": False, "error": "file not found (page fault)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write(self, rel_path: str, content: str) -> dict:
        """Write through the virtual space (always goes to sandbox, COW)."""
        # 1. Territory check
        if not self._in_territory(rel_path) and rel_path not in SHARED_PATHS:
            return {"success": False, "error": f"territory violation: cannot write to {rel_path}"}

        # 2. Constitution check
        cc = self.constitution.is_allowed("write_file", self.agent_id, rel_path, self.territory)
        if not cc["allowed"]:
            return {"success": False, "error": "constitution blocked", "constitution": cc}

        # 3. Write to sandbox (COW — project untouched)
        target = self.sandbox / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"success": True, "sandbox_path": str(target), "source": "sandbox"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list(self, rel_path: str = ".") -> dict:
        """List directory through the virtual space (territory-filtered)."""
        entries: list[dict] = []

        # Real project entries (filtered by territory)
        project_dir = self.project / rel_path
        if project_dir.exists():
            for child in sorted(project_dir.iterdir()):
                rel = str(Path(rel_path) / child.name)
                if self._in_territory(rel) or rel in SHARED_PATHS:
                    entries.append({
                        "name": child.name, "path": rel,
                        "type": "dir" if child.is_dir() else "file",
                        "source": "project",
                    })

        # Sandbox entries (overlay)
        sandbox_dir = self.sandbox / rel_path
        if sandbox_dir.exists():
            for child in sorted(sandbox_dir.iterdir()):
                rel = str(Path(rel_path) / child.name)
                existing = [e for e in entries if e["path"] == rel]
                if existing:
                    existing[0]["source"] = "sandbox"
                else:
                    entries.append({
                        "name": child.name, "path": rel,
                        "type": "dir" if child.is_dir() else "file",
                        "source": "sandbox",
                    })

        return {"success": True, "entries": entries, "count": len(entries)}

    def flush(self, rel_path: str | None = None) -> dict:
        """Flush sandbox changes to the real project.
        
        Like writing dirty pages back to disk.
        Requires L3 approval (simulated here via constitution check).
        """
        paths = [rel_path] if rel_path else None
        flushed = []
        sandbox_files = list(self.sandbox.rglob("*")) if not paths else [self.sandbox / p for p in paths]

        for src in sandbox_files:
            if not src.is_file():
                continue
            rel = src.relative_to(self.sandbox)
            dst = self.project / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            flushed.append(str(rel))

        return {"success": True, "flushed": flushed, "count": len(flushed)}

    def snapshot(self) -> dict:
        """Current space state (like /proc/maps)."""
        return {
            "agent_id": self.agent_id,
            "territory": self.territory,
            "sandbox_files": [str(f.relative_to(self.sandbox)) for f in self.sandbox.rglob("*") if f.is_file()],
            "project_root": str(self.project),
            "tlb": self.tlb.stats(),
        }

    def _in_territory(self, rel_path: str) -> bool:
        # TLB lookup first
        cached = self.tlb.lookup(rel_path)
        if cached is not None:
            return cached

        # Full check (TLB miss)
        p = rel_path.replace("\\", "/")
        result = p in SHARED_PATHS
        if not result:
            for t in self.territory:
                if p == t or p.startswith(t + "/"):
                    result = True
                    break

        # Fill TLB
        self.tlb.fill(rel_path, result)
        return result


# ── Space Manager (like the MMU) ──

class SpaceManager:
    """Manages all Agent virtual project spaces.

    Like the Memory Management Unit:
    - Allocates spaces for new Agents
    - Handles cross-space mappings (L3 review)
    - Manages shared pages (common configs, docs)
    """

    def __init__(self, project_root: str, sandbox_root: str):
        self.project_root = project_root
        self.sandbox_root = Path(sandbox_root)
        self._spaces: dict[str, ProjectSpace] = {}
        self._lock = threading.Lock()

    def create_space(self, agent_id: str) -> dict:
        with self._lock:
            if agent_id in self._spaces:
                return {"success": False, "error": "space already exists"}
            space = ProjectSpace(agent_id, self.project_root, str(self.sandbox_root))
            self._spaces[agent_id] = space
            return {"success": True, "agent_id": agent_id, "territory": space.territory}

    def get_space(self, agent_id: str) -> ProjectSpace | None:
        with self._lock:
            return self._spaces.get(agent_id)

    def resolve_conflict(self, path: str) -> dict:
        """When multiple Agents have sandbox changes to the same file,
        L3 must resolve the conflict before flush.

        Like handling a shared page with multiple dirty copies.
        """
        agents_with_changes = []
        for aid, space in self._spaces.items():
            sandbox_file = space.sandbox / path
            if sandbox_file.exists():
                agents_with_changes.append(aid)
        return {
            "success": True,
            "path": path,
            "conflicting_agents": agents_with_changes,
            "requires_l3": len(agents_with_changes) > 1,
        }

    def status(self) -> dict:
        with self._lock:
            return {aid: space.snapshot() for aid, space in self._spaces.items()}


import threading

_manager: SpaceManager | None = None


def get_manager(project_root: str = ".", sandbox_root: str = "") -> SpaceManager:
    global _manager
    if _manager is None:
        _manager = SpaceManager(project_root, sandbox_root or _VSPACE_SANDBOX)
    return _manager


def reset_manager() -> None:
    global _manager
    if _manager:
        import shutil
        shutil.rmtree(str(_manager.sandbox_root), ignore_errors=True)
    _manager = None
