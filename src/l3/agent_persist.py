"""Agent persistence — per-agent snapshot + transcript for resume and recall.

Storage layout:
  .praxis/agents/<agent_id>/
    snapshot.json      # Current execution state (overwritten every turn)
    transcript.jsonl  # Append-only execution log (never compacted)

Layered on top of:
  - CellCache (hot data, in-memory, per-Cell)
  - MemoryManager (global persistence, R1-R3)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_agent_root: Path | None = None
_lock = threading.Lock()


def _ensure_root() -> Path:
    global _agent_root
    if _agent_root is None:
        from l1.kernel.params.system import PRAXIS_DATA_DIR
        _agent_root = Path(PRAXIS_DATA_DIR) / "agents"
        _agent_root.mkdir(parents=True, exist_ok=True)
    return _agent_root


def _agent_dir(agent_id: str) -> Path:
    root = _ensure_root()
    d = root / agent_id.replace("/", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Snapshot (current execution state, overwritten every turn) ──


def save_snapshot(agent_id: str, state: dict) -> dict:
    """Save current execution state snapshot.

    Called by AgentTerminal after each card completion.
    Overwrites previous snapshot — only retains latest state.
    """
    try:
        path = _agent_dir(agent_id) / "snapshot.json"
        state["_saved_at"] = time.time()
        state["_agent_id"] = agent_id
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, default=str)
        tmp.replace(path)
        return {"success": True, "path": str(path)}
    except Exception as e:
        logger.warning("persist save_snapshot[%s]: %s", agent_id, e)
        return {"success": False, "error": str(e)}


def load_snapshot(agent_id: str) -> dict | None:
    """Load most recent snapshot for resume."""
    try:
        path = _agent_dir(agent_id) / "snapshot.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("persist load_snapshot[%s]: %s", agent_id, e)
        return None


# ── Transcript (append-only execution log, never compacted) ──


def append_transcript(agent_id: str, record: dict) -> dict:
    """Append a turn record to the transcript.

    Called by AgentTerminal after each tool execution turn.
    Append-only — never overwritten or compacted.
    Used by recall tool for cross-session search.
    """
    try:
        path = _agent_dir(agent_id) / "transcript.jsonl"
        record["_ts"] = time.time()
        record["_agent_id"] = agent_id
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return {"success": True, "path": str(path)}
    except Exception as e:
        logger.warning("persist append_transcript[%s]: %s", agent_id, e)
        return {"success": False, "error": str(e)}


def search_transcript(agent_id: str, query: str, limit: int = 20) -> list[dict]:
    """Search transcript by keyword for cross-session recall."""
    try:
        path = _agent_dir(agent_id) / "transcript.jsonl"
        if not path.exists():
            return []
        q = query.lower()
        results = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if q not in line.lower():
                    continue
                try:
                    record = json.loads(line)
                    results.append(record)
                except json.JSONDecodeError:
                    continue
                if len(results) >= limit:
                    break
        return results
    except Exception as e:
        logger.warning("persist search_transcript[%s]: %s", agent_id, e)
        return []


# ── Snapshot Hook (LifecycleHooks compatible) ──


class SnapshotHook:
    """LifecycleHook that saves snapshot and appends transcript on turn complete."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    def turn_complete(self, result: dict, elapsed: float) -> None:
        save_snapshot(self.agent_id, {
            "status": result.get("success", True),
            "summary": str(result.get("output", ""))[:200],
            "total_steps": result.get("total_steps", 0),
            "elapsed": elapsed,
        })

    def on_error(self, error: str) -> None:
        save_snapshot(self.agent_id, {
            "status": False,
            "error": str(error)[:200],
            "_saved_at": time.time(),
        })


# ── Recall tool (agent-facing, for cross-session search) ──


def recall(args: dict, agent_id: str) -> dict:
    """Recall past turns from transcript by keyword search.

    Usage (as tool handler):
      recall(query="login bug", limit=10)
    """
    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "query is required"}
    limit = int(args.get("limit", 20))
    results = search_transcript(agent_id, query, limit)
    return {"success": True, "results": results, "count": len(results)}


# ── Cleanup ──


def clear_agent(agent_id: str) -> dict:
    """Delete all persisted data for an agent."""
    try:
        d = _agent_dir(agent_id)
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
