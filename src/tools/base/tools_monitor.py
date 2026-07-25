"""Monitoring/alerting tools - 4 kinds.

alert_create, alert_list, metric_push, dashboard_query
"""

import time
import uuid
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

_alerts: list[dict] = []
_metrics: list[dict] = []


def _cmd_alert_create(args: dict, agent_id: str) -> dict:
    name = args.get("name", "")
    condition = args.get("condition", "")
    severity = args.get("severity", "info")
    if not name or not condition:
        return {"success": False, "error": "name and condition are required"}
    alert_id = str(uuid.uuid4())[:8]
    _alerts.append({
        "id": alert_id, "name": name, "condition": condition,
        "severity": severity, "created_at": time.time(), "agent_id": agent_id, "enabled": True,
    })
    return {"success": True, "data": {"alert_id": alert_id, "name": name, "severity": severity, "enabled": True}}


def _cmd_alert_list(args: dict, agent_id: str) -> dict:
    enabled_only = args.get("enabled_only", False)
    items = [a for a in _alerts if not enabled_only or a["enabled"]]
    return {"success": True, "data": {"alerts": items, "count": len(items)}}


def _cmd_metric_push(args: dict, agent_id: str) -> dict:
    name = args.get("name", "")
    value = args.get("value", 0)
    tags = args.get("tags", {})
    if not name:
        return {"success": False, "error": "name is required"}
    _metrics.append({
        "name": name, "value": value, "tags": tags,
        "agent_id": agent_id, "timestamp": time.time(),
    })
    return {"success": True, "data": {"name": name, "value": value, "recorded": True}}


def _cmd_dashboard_query(args: dict, agent_id: str) -> dict:
    period = args.get("period", "1h")
    metric = args.get("metric", "")
    if metric:
        relevant = [m for m in _metrics if m["name"] == metric]
    else:
        relevant = _metrics
    return {
        "success": True,
        "data": {
            "period": period,
            "metric": metric or "all",
            "datapoints": relevant[-100:],
            "count": len(relevant),
            "summary": {
                "avg": sum(m["value"] for m in relevant[-100:]) / max(len(relevant[-100:]), 1),
                "min": min((m["value"] for m in relevant[-100:]), default=0),
                "max": max((m["value"] for m in relevant[-100:]), default=0),
            },
        },
    }


def register_tools() -> None:
    register(ToolSpec(name="alert_create", description="Create monitoring alert rule", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("name", "string", required=True), ParamSpec("condition", "string", required=True),
                                  ParamSpec("severity", "string", default="info")],
                      handler=_cmd_alert_create))
    register(ToolSpec(name="alert_list", description="List alert rules", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("enabled_only", "bool", default=False)],
                      handler=_cmd_alert_list))
    register(ToolSpec(name="metric_push", description="Push metric data point", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("name", "string", required=True), ParamSpec("value", "int", default=0),
                                  ParamSpec("tags", "dict", default={})],
                      handler=_cmd_metric_push))
    register(ToolSpec(name="dashboard_query", description="Query dashboard data", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("period", "string", default="1h"), ParamSpec("metric", "string", default="")],
                      handler=_cmd_dashboard_query))