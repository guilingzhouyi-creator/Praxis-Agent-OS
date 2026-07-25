"""Checkpoint tools — extracted from tools_os.py for modularity."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from kernel import push_event

logger = logging.getLogger(__name__)

_checkpoints: dict[str, dict[str, Any]] = {}
_checkpoint_lock = threading.Lock()


def cmd_checkpoint_create(label: str, agent_id: str, task_id: str = "") -> dict:
    label = label or f"cp-{int(time.time())}"
    from tool_ring import get_shared_ring
    ring = get_shared_ring()
    cp = {"agent_id": agent_id, "label": label, "task_id": task_id,
          "created_at": time.time(),
          "ring_snapshot": {"count": ring.count(), "recent": [r.tool_name for r in ring.recent(5)]}}
    with _checkpoint_lock:
        _checkpoints[f"{agent_id}:{label}"] = cp
    push_event("checkpoint_created", {"agent_id": agent_id, "label": label})
    return {"success": True, "data": cp}


def cmd_checkpoint_list(agent_id: str) -> dict:
    with _checkpoint_lock:
        items = [v for k, v in _checkpoints.items() if k.startswith(f"{agent_id}:")]
    return {"success": True, "data": {"checkpoints": items, "count": len(items)}}
