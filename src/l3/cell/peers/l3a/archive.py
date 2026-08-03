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
    """List archived sessions. Fetches FULL content from DB directly —
    archive_search truncates content to LOG_TRUNC_500 which breaks
    JSON parsing for large session blobs."""
    try:
        from l3.tools._archive import _get_db
        conn = _get_db()
        if session_id:
            rows = conn.execute(
                "SELECT id, content FROM archive "
                "WHERE fonds = ? AND series = ? AND content LIKE ? "
                "ORDER BY created_at DESC LIMIT 1",
                (_p.FONDS, _p.SERIES, f"%{session_id}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, content FROM archive "
                "WHERE fonds = ? AND series = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (_p.FONDS, _p.SERIES, limit),
            ).fetchall()
    except Exception:
        capture("l3a archive: search_sessions failed", error_code="E_L3A_SEARCH",
                component="l3a", context={"session_id": session_id or ""})
        return {"success": True, "data": [], "count": 0}

    results = []
    for rid, content in rows:
        try:
            blob = json.loads(content)
            meta = blob.get("metadata", {})
            meta["_archive_id"] = rid
            results.append(meta)
        except Exception:
            capture("l3a archive: session search JSON parse failed",
                    error_code="E_L3A_ARCHIVE", component="l3a",
                    context={"session_id": session_id or ""})
            continue
    return {"success": True, "data": results, "count": len(results)}


def get_transcript(session_id: str) -> list[dict] | None:
    blob = load_session_blob(session_id)
    return blob.get("transcript") if blob else None


def load_session_blob(session_id: str) -> dict | None:
    """Load the full archived session blob (metadata + transcript + tasks + todos)."""
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
            return json.loads(row[0])
    except Exception:
        capture("l3a archive: load_session_blob failed", error_code="E_L3A_ARCHIVE",
                component="l3a", context={"session_id": session_id})
        logger.warning("l3a archive: load_session_blob failed for %s", session_id)
    return None
