"""CentralMemory — central memory dispatch & monitoring center.

Per-Cell memory instances + L3A's own instance, registered and queryable:
  get_or_create(cell_id)  → independent MemoryManager per Cell (isolated
                            persistence under memories/<cell_id>/)
  get_l3a_memory()        → L3A's own R1-R3 instance (isolated persistence
                            under memories/l3a/)
  query()                 → cross-instance recall for the L3A orchestrator
  monitor()               → per-instance pressure/stats dashboard

L3A discovers Cell/Peer memory through this center on demand (monitoring
API), rather than persisting Cell state into its own context.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from l1.kernel.params.system import MEMORY_RING_WORKING_BUDGET, MEMORY_RING_SHORT_BUDGET, MEMORY_RING_LONG_BUDGET

logger = logging.getLogger(__name__)


class CentralMemory:
    """Dispatch & monitoring center for per-Cell and L3A memory instances."""

    def __init__(self):
        self._instances: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._stats: dict[str, int] = {
            "stores": 0, "recalls": 0, "compactions": 0, "archives": 0,
        }

    # ── Instance factory / registry ──

    def _base_dir(self) -> str:
        try:
            from l1.kernel.paths import get_paths as _gp
            return os.path.join(_gp().data_dir, "memories")
        except Exception:
            return ".praxis/memories"

    def get_or_create(self, scope_id: str) -> Any:
        """Get (or lazily create) an isolated MemoryManager for a scope.

        scope_id: 'l3a' for L3A's own ring, or a Cell id like 'cell-1'.
        Each instance persists independently under memories/<scope_id>/.
        """
        with self._lock:
            mem = self._instances.get(scope_id)
            if mem is None:
                from .memory import MemoryManager
                mem = MemoryManager(
                    working_budget=MEMORY_RING_WORKING_BUDGET,
                    short_budget=MEMORY_RING_SHORT_BUDGET,
                    long_budget=MEMORY_RING_LONG_BUDGET,
                )
                persist_dir = os.path.join(self._base_dir(), scope_id)
                try:
                    os.makedirs(persist_dir, exist_ok=True)
                    mem.set_persist_dir(persist_dir)
                    mem.restore()
                except Exception as e:
                    logger.warning("central_memory: %s restore failed: %s",
                                   scope_id, e)
                self._instances[scope_id] = mem
                logger.info("central_memory: instance created for %s", scope_id)
            return mem

    def get_l3a_memory(self) -> Any:
        """L3A's own independent R1-R3 memory instance."""
        return self.get_or_create("l3a")

    def register(self, scope_id: str, mem: Any) -> None:
        """Register a pre-built memory instance under a scope id."""
        with self._lock:
            self._instances[scope_id] = mem

    def get(self, scope_id: str) -> Any | None:
        with self._lock:
            return self._instances.get(scope_id)

    def list_instances(self) -> list[dict]:
        with self._lock:
            return [{"scope": sid, "stats": self._stats_of(m)}
                    for sid, m in sorted(self._instances.items())]

    @staticmethod
    def _stats_of(mem: Any) -> dict:
        try:
            return mem.stats() if hasattr(mem, "stats") else {}
        except Exception:
            return {}

    # ── Dispatch: remember / recall / compact across instances ──

    def remember(self, agent_id: str, content: str, *,
                 entry_type: str = "observation",
                 tags: list[str] | None = None,
                 ring: int = 1,
                 importance: float = 0.5,
                 cell_id: str = "", scope_id: str = "") -> dict:
        """Store into a specific scope's instance (default: l3a scope)."""
        tags = tags or []
        self._stats["stores"] += 1
        target = scope_id or (cell_id if cell_id and cell_id != "l3a" else "l3a")

        # Quality gate (Rings 1-3)
        if ring <= 3:
            try:
                from .memory_quality import _is_good_memory, _score_importance
                accepted, reason = _is_good_memory(content, entry_type)
                if not accepted:
                    return {"success": False, "scope": target, "ring": ring,
                            "reason": f"quality_rejected:{reason}"}
                if importance == 0.5:
                    importance = _score_importance(content, entry_type)
            except Exception:
                logger.debug("central_memory: quality score failed")

        try:
            mem = self.get_or_create(target)
            r = mem.remember(agent_id=agent_id, entry_type=entry_type,
                             content=content, tags=tags, ring=ring,
                             importance=importance, cell_id=cell_id)
            if isinstance(r, str) and r.startswith("REJECTED:"):
                return {"success": False, "scope": target, "ring": ring,
                        "reason": r}
            return {"success": True, "scope": target, "ring": ring, "result": r}
        except Exception as e:
            return {"success": False, "scope": target, "error": str(e)}

    def recall(self, agent_id: str = "", *,
               query: str = "", tags: list[str] | None = None,
               rings: list[int] | None = None,
               limit: int = 20, scope_id: str = "",
               all_scopes: bool = False,
               graph_diffusion: bool = False) -> list[dict]:
        """Recall from one scope, or across ALL registered instances.

        all_scopes=True lets the L3A orchestrator search every Cell's memory
        on demand (dispatch), without persisting Cell state into its context.

        graph_diffusion=True expands results along R5 graph edges (when the
        graph is enabled) — 子图导航 from the linear hits.
        """
        tags = tags or []
        rings = rings or [1, 2, 3]
        self._stats["recalls"] += 1
        results: list[dict] = []

        scopes = []
        if all_scopes:
            with self._lock:
                scopes = list(self._instances.keys())
            if not scopes:
                scopes = ["l3a"]
        elif scope_id:
            scopes = [scope_id]
        else:
            scopes = ["l3a"]

        for sid in scopes:
            mem = self.get(sid)
            if not mem:
                continue
            try:
                entries = mem.recall(
                    agent_id=agent_id if agent_id else None,
                    entry_type=None,
                    tag=tags[0] if tags else None,
                    rings=rings, limit=limit,
                    graph_diffusion=graph_diffusion)
                for e in (entries or []):
                    d = e if isinstance(e, dict) else {
                        "id": e.id, "agent_id": e.agent_id,
                        "entry_type": e.entry_type, "content": e.content,
                        "tags": list(e.tags), "importance": e.importance,
                        "timestamp": e.timestamp,
                    }
                    d["_scope"] = sid
                    results.append(d)
            except Exception:
                logger.debug("central_memory: recall %s failed", sid)

        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return results[:limit]

    def compact(self, agent_id: str = "", ring: int = 0,
                scope_id: str = "") -> dict:
        self._stats["compactions"] += 1
        target = scope_id or "l3a"
        try:
            mem = self.get_or_create(target)
            if ring and ring <= 3:
                r = mem.compact(agent_id, ring=ring)
            else:
                r = mem.compact(agent_id)
            return {"success": True, "scope": target, "result": r}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Monitoring ──

    def monitor(self) -> dict:
        """Per-instance memory dashboard: pressure + stats for every scope."""
        with self._lock:
            scopes = list(self._instances.keys())
        instances = []
        for sid in scopes:
            mem = self.get(sid)
            if not mem:
                continue
            entry = {"scope": sid, "stats": self._stats_of(mem)}
            try:
                if hasattr(mem, "pressure"):
                    entry["pressure"] = mem.pressure()
            except Exception:
                pass
            instances.append(entry)
        return {
            "instances": instances,
            "count": len(instances),
            "cumulative": dict(self._stats),
            "time": time.time(),
        }

    def archive_ring3(self, mem_any: Any | None = None) -> dict:
        self._stats["archives"] += 1
        try:
            from .archive_orchestrator import archive_ring3
            n = archive_ring3(mem_any)
            return {"success": True, "archived": n}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stats(self) -> dict:
        base = dict(self._stats)
        base["instances"] = self.list_instances()
        try:
            from .r4_agent import get_r4_agent
            r4 = get_r4_agent()
            base["r4_stats"] = r4.status() if hasattr(r4, "status") else {}
        except Exception:
            logger.debug("central_memory: r4 stats failed")
        return base


_center: CentralMemory | None = None
_center_lock = threading.Lock()


def get_center() -> CentralMemory:
    """Return the singleton CentralMemory instance, creating it if needed."""
    global _center
    if _center is None:
        with _center_lock:
            if _center is None:
                _center = CentralMemory()
    return _center


def reset_center() -> None:
    """Reset the singleton CentralMemory instance (for testing)."""
    global _center
    _center = None


def get_cell_memory(cell_id: str) -> Any:
    """Convenience: get (or create) a Cell's isolated memory instance."""
    return get_center().get_or_create(cell_id)


def get_l3a_memory() -> Any:
    """Convenience: get L3A's own isolated memory instance."""
    return get_center().get_or_create("l3a")
