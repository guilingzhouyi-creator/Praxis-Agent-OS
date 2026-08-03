"""MerTransformer — 符号化 Mer 图旁路（定期聚合多 Agent R1-R3 → Mermaid → R4）。

设计（旁路语义）：
  1. 不干扰主记忆流程——独立模块、开关控制、失败零影响
  2. 定期聚合 CentralMemory 多 scope（Cell memories + L3A）的 R1-R3 高价值条目
  3. 符号化：条目 + 群域图边 → Mermaid flowchart（记忆的"可视化浓缩版"）
  4. 受控归档：转化产物入 R4（fonds=AGENT:l3a, series=memory_mer_snapshot）
     ——R4 是回滚基线/审计源：Mer 图错了可丢弃，原始记忆无损

开关：memory.mer.enabled（默认 false）
事件：stats.memory.mer.transform / .archived（时间总线）
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

logger = logging.getLogger(__name__)

_DEFAULT_ENABLED = False
_MER_MIN_IMPORTANCE = 0.4       # 只转化 importance >= 阈值的条目
_MER_ENTRIES_PER_SCOPE = 10     # 每 scope 最多取多少条
_MER_MAX_SCOPES = 8             # 最多聚合多少个 scope
_MER_FONDS = "AGENT:l3a"
_MER_SERIES = "memory_mer_snapshot"
_MER_ID_LEN = 8


def _default_enabled() -> bool:
    try:
        from l1.kernel.settings import get_settings
        return bool(get_settings().get("memory.mer.enabled", _DEFAULT_ENABLED))
    except Exception:
        return _DEFAULT_ENABLED


class MerTransformer:
    """符号化 Mer 图转化器（旁路）。"""

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

    # ── 聚合：多 Agent R1-R3 ──────────────────────────────

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
        """Pull graph edges for the collected nodes (if graph enabled)."""
        try:
            from l3.memory.memory_graph import get_graph
            g = get_graph()
            if not g.enabled:
                return []
            return g.semantic_edges(limit=50)
        except Exception:
            return []

    # ── 符号化：Mermaid 生成 ──────────────────────────────

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

    # ── 受控归档：入 R4 ──────────────────────────────────

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

    # ── 一次完整转化（旁路入口）──────────────────────────

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
            from l3.bus.monitor_bus import MonitorEvent as _ME
            from l3.bus.monitor_bus import get_bus as _MB
            _MB().emit(_ME(type=event_type, source="memory_mer",
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
