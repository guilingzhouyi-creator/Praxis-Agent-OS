"""R4 archive helpers — store/restore sessions."""

from __future__ import annotations

import json
import logging
from typing import Any

from . import params as _p
from l3.error_bus import capture

logger = logging.getLogger(__name__)


def store_session(session_id: str, metadata: dict,
                  transcript: list[dict]) -> dict:
    blob = json.dumps({"metadata": metadata, "transcript": transcript},
                      ensure_ascii=False, default=str)
    tags = ",".join(metadata.get("tags", ["l3a", "session"]))
    try:
        from l3.tools._archive import _cmd_archive_store
        return _cmd_archive_store(
            fonds=_p.FONDS,
            series=_p.SERIES,
            content=blob,
            tags=tags,
        )
    except Exception as e:
        capture("l3a archive: store failed", error_code="E_L3A_ARCHIVE", component="l3a", context={"session_id": session_id, "error": str(e)})
        logger.warning("l3a archive: store failed: %s", e)
        return {"success": False, "error": str(e)}


def search_sessions(limit: int = 10, cursor: str | None = None,
                    session_id: str | None = None) -> dict:
    fonds = _p.FONDS
    series = _p.SERIES
    if session_id:
        from l3.tools._archive import archive_search
        r = archive_search({
            "query": session_id,
            "fonds": fonds,
            "series": series,
            "limit": 1,
        }, agent_id=_p.AGENT_ID)
        if not r.get("success"):
            return {"success": True, "data": [], "count": 0}
        results = []
        for row in r.get("results", []):
            try:
                blob = json.loads(row.get("content", "{}"))
                meta = blob.get("metadata", {})
                meta["_archive_id"] = row.get("id")
                results.append(meta)
            except Exception:
                capture("l3a archive: session search JSON parse failed", error_code="E_L3A_ARCHIVE", component="l3a", context={"session_id": session_id})
                continue
        return {"success": True, "data": results, "count": len(results)}

    try:
        from l3.tools._archive import archive_search
        r = archive_search({
            "query": "",
            "fonds": fonds,
            "series": series,
            "limit": limit,
        }, agent_id=_p.AGENT_ID)
    except Exception:
        capture("l3a archive: search_sessions failed", error_code="E_L3A_SEARCH", component="l3a")
        return {"success": True, "data": [], "count": 0}
    if not r.get("success"):
        return {"success": True, "data": [], "count": 0}
    results = []
    for row in r.get("results", []):
        try:
            blob = json.loads(row.get("content", "{}"))
            meta = blob.get("metadata", {})
            meta["_archive_id"] = row.get("id")
            results.append(meta)
        except Exception:
            continue
    return {"success": True, "data": results, "count": len(results)}


def get_transcript(session_id: str) -> list[dict] | None:
    r = search_sessions(session_id=session_id, limit=1)
    if r["count"] == 0:
        return None
    arch_id = r["data"][0].get("_archive_id")
    if not arch_id:
        return None
    try:
        from l3.tools._archive import _get_db
        conn = _get_db()
        row = conn.execute(
            "SELECT content FROM archive WHERE id = ?", (arch_id,)
        ).fetchone()
        if row:
            blob = json.loads(row[0])
            return blob.get("transcript")
    except Exception:
        capture("l3a archive: get_transcript failed", error_code="E_L3A_ARCHIVE", component="l3a", context={"session_id": session_id})
        logger.warning("l3a archive: get_transcript failed for %s", session_id)
    return None
