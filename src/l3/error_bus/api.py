"""ErrorBus API handlers — REST endpoints for error log frontend."""


def _parse_float(body: dict, key: str) -> float | None:
    raw = body.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _parse_int(body: dict, key: str, default: int = 0) -> int:
    raw = body.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def handle_log_errors(body: dict | None = None) -> dict:
    """Handle error log query. Returns matching log entries."""
    b = body or {}
    from . import get_bus

    bus = get_bus()
    return bus.query(
        level=b.get("level"),
        error_code=b.get("error_code"),
        component=b.get("component"),
        service=b.get("service"),
        agent_id=b.get("agent_id"),
        since=_parse_float(b, "since"),
        until=_parse_float(b, "until"),
        offset=_parse_int(b, "offset", 0),
        limit=_parse_int(b, "limit", 50),
    )


def handle_log_errors_detail(body: dict | None = None) -> dict:
    """Handle error log detail query by fingerprint. Returns the entry."""
    b = body or {}
    fingerprint = b.get("fingerprint", "")
    if not fingerprint:
        return {"success": False, "error": "fingerprint is required"}
    from . import get_bus

    entry = get_bus().get_by_fingerprint(fingerprint)
    if entry is None:
        return {"success": False, "error": "not found"}
    return {"success": True, "entry": entry}


def handle_log_errors_stats(body: dict | None = None) -> dict:
    """Handle error log statistics query. Returns the stats dict."""
    from . import get_bus

    return get_bus().stats()


def handle_log_errors_trend(body: dict | None = None) -> dict:
    """Handle error log trend query. Returns the trend buckets."""
    b = body or {}
    window = _parse_int(b, "window", 60)
    bucket = _parse_int(b, "bucket", 10)
    from . import get_bus

    return get_bus().trend(window_minutes=window, bucket_minutes=bucket)


def handle_log_errors_clear(body: dict | None = None) -> dict:
    """Handle error log clear. Returns the removal result."""
    b = body or {}
    before = _parse_float(b, "before")
    from . import get_bus

    return get_bus().clear(before=before)


def handle_log_errors_export(body: dict | None = None) -> dict:
    """Handle error log export to JSON. Returns the export result."""
    b = body or {}
    path = b.get("path", "")
    from . import get_bus

    return get_bus().export(path=path)
