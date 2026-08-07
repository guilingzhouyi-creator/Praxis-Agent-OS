"""CardExecutionStatsMixin — per-executor timing attribution for CardRegistry.

Extracted from card_registry.py (P2 split).  ``_CardExecution`` is imported
lazily from the parent module to avoid a circular import.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from l1.kernel.params.system import LOG_TRUNC_80

if TYPE_CHECKING:
    from l3.card.card_unified import CardUnified

logger = logging.getLogger(__name__)


class CardExecutionStatsMixin:
    """CardExecutionStatsMixin — record, expose and aggregate card timing."""

    # ── Attributes injected by the concrete CardRegistry (see card_registry.py) ──
    _lock: threading.RLock
    _cards: dict[str, CardUnified]

    def _record_card_executions(self, card_id: str, cell_id: str,
                                cell_elapsed: float, result: dict) -> None:
        """Attach per-executor wall-time to the card record.

        Granularity:
          one cell-level entry (executor == cell_id)
          one entry per Peer Agent step (from ExecutionPlan step results)
        """
        from l3.card.card_registry import _CardExecution
        with self._lock:
            rec = self._cards.get(card_id)
            if not rec:
                return
            now = time.time()
            rec.executions.append(_CardExecution(
                executor=cell_id, cell_id=cell_id, phase="cell",
                started_at=now - cell_elapsed, finished_at=now,
                elapsed=cell_elapsed,
                success=bool(result and result.get("success")),
            ))
            seen: dict[str, float] = {}
            steps = (result or {}).get("steps", []) or []
            if not steps and result:
                steps = result.get("results", []) or []
            for st in steps:
                if not isinstance(st, dict):
                    continue
                aid = st.get("agent_id", "")
                if not aid:
                    continue
                el = float(st.get("elapsed", 0) or 0)
                if aid in seen:
                    seen[aid] += el
                    continue
                seen[aid] = el
            rec.executions.append(_CardExecution(
                    executor=aid, cell_id=cell_id,
                    phase=st.get("phase", "step"),
                    started_at=now - cell_elapsed, finished_at=now,
                    elapsed=el, success=bool(st.get("success")),
                ))

    def _expose_card_execution(self, card_id: str, cell_id: str,
                               cell_elapsed: float, result: dict) -> None:
        """Publish card end-to-end timing to monitoring + statistics centers."""
        try:
            rec = self._cards.get(card_id)
            total = 0.0
            if rec and rec.timestamps.completed_at and rec.timestamps.created_at:
                total = round(rec.timestamps.completed_at - rec.timestamps.created_at, 3)
        except Exception:
            total = 0.0
        agents: dict[str, float] = {}
        for e in getattr(rec, "executions", []) or []:
            if e.executor and e.executor != cell_id:
                agents[e.executor] = agents.get(e.executor, 0.0) + e.elapsed
        try:
            from l3.bus.monitor_bus import MonitorEvent as _ME5
            from l3.bus.monitor_bus import get_bus as _MB5
            _MB5().emit(_ME5(
                type="stats.card.execution", source="card_registry",
                severity="info",
                message=f"{card_id} cell={cell_id} {cell_elapsed}s agents={len(agents)}",
                card_id=card_id, cell_id=cell_id,
                data={"card_id": card_id, "cell_id": cell_id,
                      "cell_elapsed": cell_elapsed,
                      "total_elapsed": total,
                      "agents": agents,
                      "success": bool(result and result.get("success"))}))
        except Exception:
            logger.debug("card_registry: monitor emit failed")
        try:
            from l3.services.stats_center import MetricPoint as _MP5
            from l3.services.stats_center import get_center as _SC5
            _ts = time.time()
            _tags = {"card": card_id, "cell": cell_id}
            _SC5().ingest(_MP5(name="card.execution.total", value=total,
                               tags=_tags, timestamp=_ts, metric_type="gauge"))
            _SC5().ingest(_MP5(name="card.execution.cell", value=cell_elapsed,
                               tags=_tags, timestamp=_ts, metric_type="gauge"))
            for aid, el in agents.items():
                _SC5().ingest(_MP5(name="card.execution.agent", value=round(el, 3),
                                   tags={"card": card_id, "cell": cell_id, "agent": aid},
                                   timestamp=_ts, metric_type="gauge"))
        except Exception:
            logger.debug("card_registry: stats emit failed")

    def execution_stats(self, limit: int = 20) -> dict:
        """Card end-to-end timing with per-Cell and per-Peer-Agent breakdown.

        Returns:
          cards:      per-card total (created→completed) + cell + agent sums
          by_cell:    aggregated cell wall-time across cards
          by_agent:   aggregated per-Peer-Agent wall-time across cards
        """
        with self._lock:
            cards = []
            by_cell: dict[str, dict] = {}
            by_agent: dict[str, dict] = {}
            for r in sorted(self._cards.values(),
                            key=lambda x: x.timestamps.completed_at or 0,
                            reverse=True):
                if not r.executions:
                    continue
                total = 0.0
                if r.timestamps.completed_at and r.timestamps.created_at:
                    total = round(r.timestamps.completed_at - r.timestamps.created_at, 3)
                cell_t = 0.0
                agent_t: dict[str, float] = {}
                for e in r.executions:
                    if e.executor == e.cell_id:
                        cell_t += e.elapsed
                    else:
                        agent_t[e.executor] = agent_t.get(e.executor, 0.0) + e.elapsed
                cards.append({
                    "card_id": r.id,
                    "state": r.state.value,
                    "title": r.summary.title[:LOG_TRUNC_80],
                    "total_elapsed": total,
                    "cell_elapsed": round(cell_t, 3),
                    "agents": {k: round(v, 3) for k, v in agent_t.items()},
                    "executions": [e.to_dict() for e in r.executions],
                })
                for e in r.executions:
                    if e.executor == e.cell_id:
                        agg = by_cell.setdefault(e.cell_id,
                                                 {"cards": 0, "elapsed": 0.0})
                        agg["cards"] += 1
                        agg["elapsed"] += e.elapsed
                    else:
                        agg = by_agent.setdefault(e.executor,
                                                  {"cards": 0, "elapsed": 0.0})
                        agg["cards"] += 1
                        agg["elapsed"] += e.elapsed
                if len(cards) >= limit:
                    break
            return {
                "cards": cards,
                "by_cell": {k: {"cards": v["cards"],
                                "elapsed": round(v["elapsed"], 3)}
                            for k, v in by_cell.items()},
                "by_agent": {k: {"cards": v["cards"],
                                 "elapsed": round(v["elapsed"], 3)}
                             for k, v in by_agent.items()},
            }
