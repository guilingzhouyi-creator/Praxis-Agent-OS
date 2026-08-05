"""MerTransformer — symbolic Mer graph bypass (periodic aggregation of multi-agent R1-R3 → Mermaid → R4).

Design (bypass semantics):
  1. Does not interfere with the main memory flow — independent module, toggle-controlled, zero impact on failure
  2. Periodically aggregates CentralMemory multi-scope (Cell memories + L3A) high-value R1-R3 entries
  3. Symbolization: entries + swarm-domain graph edges → Mermaid flowchart (a "visualized condensed version" of memory)
  4. Controlled archiving: transformation products into R4 (fonds=AGENT:l3a, series=memory_mer_snapshot)
     — R4 is the rollback baseline / audit source: Mer graph can be discarded on error, original memory intact

Toggle: memory.mer.enabled (default false)
Events: stats.memory.mer.transform / .archived (time bus)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from l1.kernel.params.system import LOG_TRUNC_50

logger = logging.getLogger(__name__)

_DEFAULT_ENABLED = False
_MER_MIN_IMPORTANCE = 0.4       # transform only entries with importance >= threshold
_MER_ENTRIES_PER_SCOPE = 10     # max entries per scope
_MER_MAX_SCOPES = 8             # max scopes aggregated
# Normalized form (archive _normalize_fonds lowercases and strips non [a-z0-9_-])
_MER_FONDS = "agent-l3a"
_MER_SERIES = "memory_mer_snapshot"
_MER_ID_LEN = 8


def _default_enabled() -> bool:
    try:
        from l1.kernel.settings import get_settings
        return bool(get_settings().get("memory.mer.enabled", _DEFAULT_ENABLED))
    except Exception:
        return _DEFAULT_ENABLED


class MerTransformer:
    """Symbolic Mer graph transformer (bypass)."""

    def __init__(self, enabled: bool | None = None):
        self._enabled = _default_enabled() if enabled is None else enabled
        self._lock = threading.RLock()
        self._stats: dict = {"transforms": 0, "archived": 0}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, flag: bool) -> None:
        changed = self._enabled != bool(flag)
        self._enabled = bool(flag)
        logger.info("memory_mer: enabled=%s", self._enabled)
        if changed:
            self._emit_event("stats.memory.mer.switch", {"enabled": self._enabled})

    # ── Aggregation: multi-agent R1-R3 ──────────────────────────────

    def collect_entries(self, scope_ids: list[str] | None = None,
                        limit: int = _MER_ENTRIES_PER_SCOPE) -> list[dict]:
        """Aggregate high-value R1-R3 entries across scopes."""
        try:
            from l3.memory.central_memory import get_center
        except Exception:
            return []
        center = get_center()
        scopes = scope_ids or []
        if not scopes:
            try:
                insts = center.list_instances()
                scopes = [i.get("scope_id", "") for i in insts][:_MER_MAX_SCOPES]
            except Exception:
                scopes = ["l3a"]
        out: list[dict] = []
        for sid in scopes:
            try:
                mem = center.get(sid)
                if mem is None:
                    continue
                entries = mem.recall(agent_id=None, rings=[1, 2, 3], limit=limit)
                for e in (entries or []):
                    d = e if isinstance(e, dict) else {
                        "id": e.id, "agent_id": e.agent_id,
                        "entry_type": e.entry_type, "content": e.content,
                        "importance": getattr(e, "importance", 0.5),
                        "timestamp": getattr(e, "timestamp", 0.0),
                    }
                    if float(d.get("importance", 0)) >= _MER_MIN_IMPORTANCE:
                        d["_scope"] = sid
                        out.append(d)
            except Exception:
                continue
        out.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return out

    def collect_edges(self, node_ids: list[str]) -> list[dict]:
        """Pull graph edges among the collected nodes (if graph enabled)."""
        try:
            from l3.memory.memory_graph import get_graph
            g = get_graph()
            if not g.enabled:
                return []
            node_set = set(node_ids or [])
            edges = g.semantic_edges(limit=100)
            if not node_set:
                return edges[:LOG_TRUNC_50]
            return [ed for ed in edges
                    if ed.get("from_id") in node_set or ed.get("to_id") in node_set][:LOG_TRUNC_50]
        except Exception:
            return []

    # ── Symbolization: Mermaid generation ──────────────────────────────

    def to_mermaid(self, entries: list[dict], edges: list[dict] | None = None,
                   title: str = "Memory") -> str:
        """Render collected entries + edges as a Mermaid flowchart."""
        lines = ["flowchart LR"]
        nid: dict[str, str] = {}
        for i, e in enumerate(entries):
            key = f"e{i}"
            nid[e.get("id", "")] = key
            label = (e.get("entry_type", "?") + ": "
                     + str(e.get("content", ""))[:40].replace('"', "'"))
            lines.append(f'    {key}["{label}"]')
        for ed in (edges or []):
            f = nid.get(ed.get("from_id", ""))
            t = nid.get(ed.get("to_id", ""))
            if f and t:
                lines.append(f'    {f} -->|{ed.get("relation", "related")}| {t}')
        lines.insert(1, f'    subgraph {title.replace(" ", "_")}')
        lines.append("    end")
        return "\n".join(lines)

    # ── Controlled archiving: to R4 ──────────────────────────────────

    def archive_to_r4(self, mermaid: str, meta: dict | None = None) -> dict:
        """Archive the Mer graph to R4 (audit baseline, recoverable)."""
        ts = int(time.time())
        try:
            import json as _json

            from l3.tools._archive import _cmd_archive_store
            payload = _json.dumps({
                "mermaid": mermaid,
                "meta": meta or {},
                "generated_at": time.time(),
            }, ensure_ascii=False)
            r = _cmd_archive_store(
                fonds=_MER_FONDS, series=_MER_SERIES,
                content=payload,
                tags=f"l3a,memory_mer,{meta.get('scope_ids', '') if meta else ''}")
            if not r.get("success"):
                return {"success": False, "error": "archive store failed"}
            return {"success": True,
                    "archive_ref": f"{_MER_FONDS}:{_MER_SERIES}:{ts}"}
        except Exception as e:
            logger.debug("memory_mer: R4 archive failed: %s", e)
            return {"success": False, "error": str(e)}

    # ── One full transform (bypass entry) ──────────────────────────

    def transform_and_archive(self, scope_ids: list[str] | None = None) -> dict:
        """Full side-channel pass: collect → symbolize → archive to R4."""
        if not self._enabled:
            return {"success": False, "archived": 0, "error": "disabled"}
        try:
            entries = self.collect_entries(scope_ids)
            if not entries:
                return {"success": True, "archived": 0, "entries": 0}
            edges = self.collect_edges([e["id"] for e in entries])
            mermaid = self.to_mermaid(entries, edges,
                                      title=f"mer-{uuid.uuid4().hex[:_MER_ID_LEN]}")
            meta = {"scope_ids": list({e.get("_scope", "") for e in entries}),
                    "entries": len(entries), "edges": len(edges)}
            arc = self.archive_to_r4(mermaid, meta)
            with self._lock:
                self._stats["transforms"] += 1
                if arc.get("success"):
                    self._stats["archived"] += 1
            self._emit_event("stats.memory.mer.transform", {
                **meta, "archived": arc.get("success", False),
                "archive_ref": arc.get("archive_ref", ""),
            })
            return {"success": True, "archived": 1 if arc.get("success") else 0,
                    "entries": len(entries), "edges": len(edges),
                    "mermaid": mermaid, "archive_ref": arc.get("archive_ref", "")}
        except Exception as e:
            logger.debug("memory_mer: transform failed: %s", e)
            return {"success": False, "archived": 0, "error": str(e)}

    def stats(self) -> dict:
        with self._lock:
            return {"enabled": self._enabled, **dict(self._stats)}

    def _emit_event(self, event_type: str, data: dict) -> None:
        try:
            from l3.bus.monitor_bus import MonitorEvent as _MEv
            from l3.bus.monitor_bus import get_bus as _MB
            _MB().emit(_MEv(type=event_type, source="memory_mer",
                           severity="info", data=data))
        except Exception:
            logger.debug("memory_mer: monitor emit failed")


# ── Module-level singleton (conftest-resettable) ─────────

_mer: MerTransformer | None = None
_mer_lock = threading.Lock()


def get_mer() -> MerTransformer:
    global _mer
    if _mer is None:
        with _mer_lock:
            if _mer is None:
                _mer = MerTransformer()
    return _mer


def reset_mer() -> None:
    global _mer
    with _mer_lock:
        _mer = None
