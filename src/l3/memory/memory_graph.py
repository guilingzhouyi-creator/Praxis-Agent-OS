"""MemoryGraph — R5 群域图层：R1-R4 之上的语义拓扑索引。

分层定位：
  R1-R3  操作记忆（agent 运行时快速存取）
  R4     无损档案（全量、可回滚、审计基线）
  R5     群域图（本模块）——档案的语义拓扑索引：
           节点 = 各环的 MemEntry（天然节点：id/type/tags/importance）
           边   = 规则建边（sequential / type_chain / cell_chain）
           检索 = 扩散激活（种子沿边遍历）
           压缩 = 图约简（度中心性：保留 hub 剪叶子）

治理语义：
  - 开关：enabled（默认 false——读 settings ``memory.graph.enabled``）
  - 归因：每条边记录 created_by（谁建的边）
  - 派生：图可从 R4 重建（出错不影响档案，档案是 ground truth）
  - 隔离：每个 MemoryManager 实例持有独立图（scope 隔离）

存储：SQLite ``memory_edges`` 表（独立库，与 knowledge 表分离）。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_EDGE_ID_LEN = 12

_REL_SEQUENTIAL = "sequential"      # 同 agent 连续写入链
_REL_TYPE_CHAIN = "type_chain"      # 同 agent + 同 entry_type 链
_REL_CELL_CHAIN = "cell_chain"      # 同 cell 链

_DEFAULT_DB_NAME = "memory_graph.db"
_DEFAULT_ENABLED = False


def _default_enabled() -> bool:
    """Read the global switch from settings (memory.graph.enabled)."""
    try:
        from l1.kernel.settings import get_settings
        return bool(get_settings().get("memory.graph.enabled", _DEFAULT_ENABLED))
    except Exception:
        return _DEFAULT_ENABLED


class MemoryGraph:
    """群域图引擎：边表管理 + 规则建边 + 扩散检索 + 图约简。"""

    def __init__(self, db_path: str = "", enabled: bool | None = None):
        self._enabled = _default_enabled() if enabled is None else enabled
        self._lock = threading.RLock()
        self._db_path = db_path or str(Path.cwd() / _DEFAULT_DB_NAME)
        self._conn: sqlite3.Connection | None = None
        self._connect()

    # ── 存储 ────────────────────────────────────────────────

    def _connect(self) -> None:
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_edges (
                    id         TEXT PRIMARY KEY,
                    from_id    TEXT NOT NULL,
                    to_id      TEXT NOT NULL,
                    relation   TEXT NOT NULL,
                    weight     REAL DEFAULT 1.0,
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at REAL NOT NULL
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_from ON memory_edges(from_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_to ON memory_edges(to_id)")
            self._conn.commit()
        except Exception as e:
            logger.warning("memory_graph: connect failed: %s", e)
            self._conn = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, flag: bool) -> None:
        self._enabled = bool(flag)
        logger.info("memory_graph: enabled=%s", self._enabled)

    # ── 规则建边（零成本，无 LLM）────────────────────────────

    def remember_hook(self, entry_id: str, agent_id: str, entry_type: str,
                      cell_id: str, recent: list[dict],
                      created_by: str = "system") -> list[str]:
        """Called after remember(): build rule-based edges to recent entries.

        Args:
            recent: list of {"id", "entry_type", "agent_id", "cell_id"} for
                    the most recent entries (provided by MemoryManager).
        Returns: list of created edge ids (empty when disabled).
        """
        if not self._enabled or self._conn is None:
            return []
        created: list[str] = []
        now = time.time()
        try:
            with self._lock:
                for r in recent:
                    if not r or r.get("id") == entry_id:
                        continue  # never self-loop
                    rel = ""
                    w = 1.0
                    if r.get("agent_id") == agent_id:
                        rel = _REL_SEQUENTIAL
                        w = 1.0
                        if entry_type and r.get("entry_type") == entry_type:
                            rel = _REL_TYPE_CHAIN  # 同 agent + 同类型 = 最强
                            w = 1.2
                    elif r.get("cell_id") and r.get("cell_id") == cell_id:
                        rel = _REL_CELL_CHAIN
                        w = 0.8
                    if not rel:
                        continue
                    if self._edge_exists(r["id"], entry_id, rel):
                        continue
                    eid = self._insert_edge(
                        from_id=r["id"], to_id=entry_id, relation=rel,
                        weight=w, created_by=created_by, created_at=now)
                    if eid:
                        created.append(eid)
        except Exception as e:
            logger.debug("memory_graph: remember_hook failed: %s", e)
        return created

    def _edge_exists(self, from_id: str, to_id: str, relation: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM memory_edges WHERE from_id=? AND to_id=? AND relation=? LIMIT 1",
            (from_id, to_id, relation))
        return cur.fetchone() is not None

    def _insert_edge(self, from_id: str, to_id: str, relation: str,
                     weight: float, created_by: str, created_at: float) -> str | None:
        eid = f"edge-{uuid.uuid4().hex[:_EDGE_ID_LEN]}"
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO memory_edges "
                "(id, from_id, to_id, relation, weight, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (eid, from_id, to_id, relation, weight, created_by, created_at))
            self._conn.commit()
            return eid
        except Exception as e:
            logger.debug("memory_graph: insert failed: %s", e)
            return None

    # ── 扩散检索（种子沿边遍历）──────────────────────────────

    def recall(self, seeds: list[str], depth: int = 2,
               limit: int = 20) -> dict:
        """Diffusion retrieval: BFS from seed entries.

        Returns:
            {"nodes": [entry_id...], "edges": [{from_id, to_id, relation, weight}],
             "stats": {"seeds": N, "depth": D, "reached": N}}
        """
        if not self._enabled or self._conn is None:
            return {"nodes": [], "edges": [], "stats": {"seeds": len(seeds), "depth": 0, "reached": 0}}
        reached: dict[str, int] = {}
        frontier: list[str] = [s for s in seeds if s]
        for d in range(max(1, depth)):
            nxt: list[str] = []
            for fid in frontier:
                if fid in reached:
                    continue
                reached[fid] = d + 1
                try:
                    cur = self._conn.execute(
                        "SELECT to_id FROM memory_edges WHERE from_id=? "
                        "UNION SELECT from_id FROM memory_edges WHERE to_id=?",
                        (fid, fid))
                    for row in cur.fetchall():
                        nxt.append(row[0])
                except Exception:
                    break
            if not nxt:
                break
            frontier = nxt
        nodes = list(reached.keys())[:limit]
        edges: list[dict] = []
        try:
            cur = self._conn.execute(
                "SELECT from_id, to_id, relation, weight FROM memory_edges "
                "WHERE from_id IN (%s) OR to_id IN (%s) LIMIT %d"
                % (",".join("?" * len(nodes)), ",".join("?" * len(nodes)), limit * 2),
                list(nodes) + list(nodes))
            for fid, tid, rel, w in cur.fetchall():
                edges.append({"from_id": fid, "to_id": tid,
                              "relation": rel, "weight": w})
        except Exception:
            pass
        return {"nodes": nodes, "edges": edges,
                "stats": {"seeds": len(seeds), "depth": depth, "reached": len(nodes)}}

    # ── 图约简（度中心性分析）────────────────────────────────

    def compact_report(self, min_degree: int = 2) -> dict:
        """Graph reduction analysis: keep hubs, prune leaves.

        Returns (read-only analysis — actual pruning is a policy decision):
            {"hubs": [{"entry_id", "degree"}], "leaves": N, "edges": N}
        """
        if self._conn is None:
            return {"hubs": [], "leaves": 0, "edges": 0}
        try:
            cur = self._conn.execute(
                "SELECT entry, COUNT(*) AS deg FROM ("
                "  SELECT from_id AS entry FROM memory_edges "
                "  UNION ALL SELECT to_id AS entry FROM memory_edges"
                ") GROUP BY entry")
            degrees = {row[0]: row[1] for row in cur.fetchall()}
            hubs = [{"entry_id": eid, "degree": deg}
                    for eid, deg in degrees.items() if deg >= min_degree]
            leaves = sum(1 for deg in degrees.values() if deg == 1)
            total_edges = self._conn.execute(
                "SELECT COUNT(*) FROM memory_edges").fetchone()[0]
            return {"hubs": hubs, "leaves": leaves, "edges": total_edges}
        except Exception as e:
            logger.debug("memory_graph: compact_report failed: %s", e)
            return {"hubs": [], "leaves": 0, "edges": 0}

    # ── 查询 / 维护 ─────────────────────────────────────────

    def edges_of(self, entry_id: str, limit: int = 20) -> list[dict]:
        if self._conn is None:
            return []
        try:
            cur = self._conn.execute(
                "SELECT from_id, to_id, relation, weight, created_by, created_at "
                "FROM memory_edges WHERE from_id=? OR to_id=? LIMIT ?",
                (entry_id, entry_id, limit))
            return [{"from_id": r[0], "to_id": r[1], "relation": r[2],
                     "weight": r[3], "created_by": r[4], "created_at": r[5]}
                    for r in cur.fetchall()]
        except Exception:
            return []

    def stats(self) -> dict:
        if self._conn is None:
            return {"enabled": self._enabled, "edges": 0, "db": self._db_path}
        try:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM memory_edges").fetchone()[0]
            by_rel: dict[str, int] = {}
            for row in self._conn.execute(
                    "SELECT relation, COUNT(*) FROM memory_edges GROUP BY relation"):
                by_rel[row[0]] = row[1]
            return {"enabled": self._enabled, "edges": total,
                    "by_relation": by_rel, "db": self._db_path}
        except Exception:
            return {"enabled": self._enabled, "edges": 0, "db": self._db_path}

    def clear(self) -> int:
        if self._conn is None:
            return 0
        try:
            with self._lock:
                n = self._conn.execute("DELETE FROM memory_edges").rowcount
                self._conn.commit()
                return n
        except Exception:
            return 0

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# ── Module-level singleton (conftest-resettable) ─────────────

_graph: MemoryGraph | None = None
_graph_lock = threading.Lock()


def get_graph(db_path: str = "") -> MemoryGraph:
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = MemoryGraph(db_path=db_path)
    return _graph


def reset_graph() -> None:
    global _graph
    with _graph_lock:
        if _graph is not None:
            try:
                _graph.close()
            except Exception:
                pass
            _graph = None
