"""StatsCenter API handlers — query/top/live endpoints.

Endpoints:
  POST /api/v2/stats/query  — aggregated metric query
  GET  /api/v2/stats/top    — cross-Cell ranking
  SSE  /api/v2/stats/live   — real-time metric stream
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def handle_stats_query(body: dict | None = None) -> dict:
    """POST /api/v2/stats/query — aggregated metric query.

    Body:
      metrics: list[str]  — metric names (default all)
      tags:    dict        — filter by tag key=value
      window:  str         — "1m", "5m", "1h", "all" (default "5m")
      agg:     str         — "sum"|"avg"|"min"|"max"|"last"|"p95" (default "sum")

    Returns:
      {"success": true, "results": [...], "stats": {...}}
    """
    b = body or {}
    try:
        from l3.services.stats_center import get_center
        center = get_center()
        results = center.query(
            metrics=b.get("metrics"),
            tags=b.get("tags"),
            window=b.get("window", "5m"),
            agg=b.get("agg", "sum"),
        )
        return {"success": True, "results": results, "stats": center.stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_stats_top(body: dict | None = None) -> dict:
    """GET /api/v2/stats/top — cross-Cell ranking.

    Query params (via body or query string):
      metric: str   — metric name (required)
      order:  str   — "desc"|"asc" (default "desc")
      limit:  int   — max results (default 10)
      window: str   — time window (default "5m")

    Returns:
      {"success": true, "metric": "...", "ranking": [...], "stats": {...}}
    """
    b = body or {}
    metric = b.get("metric", "")
    if not metric:
        return {"success": False, "error": "metric required"}
    try:
        from l3.services.stats_center import get_center
        center = get_center()
        ranking = center.top(
            metric=metric,
            order=b.get("order", "desc"),
            limit=int(b.get("limit", 10)),
            window=b.get("window", "5m"),
        )
        return {"success": True, "metric": metric, "ranking": ranking, "stats": center.stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_stats_live(body: dict | None = None) -> dict:
    """SSE /api/v2/stats/live — real-time metric stream (polling fallback).

    Returns recent buffered events for SSE clients that poll via POST
    (fallback when native SSE is unavailable).
    """
    try:
        from l3.bus.monitor_bus import get_bus as get_monitor
        from l3.services.stats_center import get_center

        center = get_center()
        monitor = get_monitor()

        # Query recent MonitorEvents with type "stats.*" or return center stats
        events = monitor.query(type_prefix="stats.*", limit=STATS_SSE_BUFFER)
        return {
            "success": True,
            "events": events,
            "stats": center.stats(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# Dragged from params for import independence
STATS_SSE_BUFFER = 100
