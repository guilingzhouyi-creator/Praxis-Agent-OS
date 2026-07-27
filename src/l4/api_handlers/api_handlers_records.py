"""RecordCenter API handlers — unified error/log/reference query + export.

Endpoints:
  POST /api/v2/records/query  — unified query across error/log/reference
  GET  /api/v2/records/stats  — aggregated stats from all stores
  POST /api/v2/records/export — export to JSON with retention
  POST /api/v2/records/bridge — push aggregate metrics to StatsCenter
"""

from __future__ import annotations

import logging
from typing import Any

from l3.services.record_center import get_record_center, RecordQuery

logger = logging.getLogger(__name__)


def handle_records_query(body: dict | None = None) -> dict:
    """POST /api/v2/records/query — unified query.

    Body:
      sources:  list[str]  — "error", "log", "reference" (default all)
      level:    str        — filter by level
      service:  str        — filter by service name
      agent_id: str        — filter by agent
      error_code: str      — filter by error code
      component: str       — filter by component
      keyword:  str        — full-text search across all fields
      since:    float      — unix timestamp start
      until:    float      — unix timestamp end
      offset:   int        — pagination offset
      limit:    int        — max results (default 50)
    """
    b = body or {}
    q = RecordQuery(
        sources=b.get("sources"),
        level=b.get("level", ""),
        service=b.get("service", ""),
        agent_id=b.get("agent_id", ""),
        error_code=b.get("error_code", ""),
        component=b.get("component", ""),
        since=float(b.get("since", 0)),
        until=float(b.get("until", 0)),
        offset=int(b.get("offset", 0)),
        limit=int(b.get("limit", 50)),
        keyword=b.get("keyword", ""),
    )
    try:
        rc = get_record_center()
        return rc.query(q)
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_records_stats(body: dict | None = None) -> dict:
    """GET /api/v2/records/stats — aggregated stats."""
    try:
        rc = get_record_center()
        return rc.stats()
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_records_export(body: dict | None = None) -> dict:
    """POST /api/v2/records/export — export to JSON.

    Body:
      path:    str        — export file path (optional, auto-generated)
      sources: list[str]  — which sources to export (default all)
    """
    b = body or {}
    try:
        rc = get_record_center()
        return rc.export(
            path=b.get("path", ""),
            sources=b.get("sources"),
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_records_bridge(body: dict | None = None) -> dict:
    """POST /api/v2/records/bridge — push aggregate metrics to StatsCenter."""
    try:
        rc = get_record_center()
        rc.bridge_stats()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
