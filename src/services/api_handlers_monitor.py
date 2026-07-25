"""API handlers for Token/Monitor/Export operations — extracted from api_handlers.py."""
from __future__ import annotations
from typing import Any


def token_stats(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        c = get_counter()
        window = float(body.get("window", 0)) if body else 0
        if window > 0:
            return {"rate": c.token_rate(window), "summary": c.token_summary()}
        return {"summary": c.token_summary()}
    except Exception as e:
        return {"error": str(e)}


def token_cells(body: dict | None = None) -> dict:
    try:
        from services.central_collector import get_collector
        return {"cells": get_collector().cell_summary()}
    except Exception as e:
        return {"error": str(e)}


def token_global(body: dict | None = None) -> dict:
    try:
        from services.central_collector import get_collector
        return get_collector().global_summary()
    except Exception as e:
        return {"error": str(e)}


def comm_stats(body: dict | None = None) -> dict:
    try:
        from services.comm_monitor import get_monitor
        return get_monitor().stats()
    except Exception as e:
        return {"error": str(e)}


def comm_recent(body: dict | None = None) -> dict:
    try:
        limit = int((body or {}).get("limit", 50))
        from services.comm_monitor import get_monitor
        return {"recent": get_monitor().recent(limit)}
    except Exception as e:
        return {"error": str(e)}


def loop_stats(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        return get_counter().loop_summary()
    except Exception as e:
        return {"error": str(e)}


def loops_recent(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        c = get_counter()
        limit = int((body or {}).get("limit", 20))
        return {"loops": c._all_loops[-limit:]}
    except Exception as e:
        return {"error": str(e)}


def export_counter(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        return get_counter().export()
    except Exception as e:
        return {"error": str(e)}


def export_metrics(body: dict | None = None) -> dict:
    try:
        from services.counter import get_counter
        return {"metrics": get_counter().export_metrics()}
    except Exception as e:
        return {"error": str(e)}


def network_health(body: dict | None = None) -> dict:
    try:
        from kernel.net import get_net
        return get_net().health()
    except Exception as e:
        return {"error": str(e)}
