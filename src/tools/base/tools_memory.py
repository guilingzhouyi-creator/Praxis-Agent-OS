"""Memory tools - 6 kinds.

memory_store, memory_retrieve, memory_search, memory_forget, memory_list, memory_stats

Backed by the main MemoryManager service (not a private dict).
"""

import json
import time
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R
from services.memory import get_memory
from kernel.params import TOOL_MEMORY_RECALL_LIMIT, TOOL_MEMORY_RECALL_LARGE


def _ttl_to_ring(ttl: int) -> int:
    """Map a TTL in seconds to an appropriate ring level."""
    if ttl <= 1800:
        return 1   # Working memory
    if ttl <= 86400:
        return 2   # Short-term
    return 3       # Long-term


def _cmd_memory_store(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    data = args.get("data", "")
    namespace = args.get("namespace", "default")
    ttl = args.get("ttl", 3600)
    if not key or not data:
        return {"success": False, "error": "key and data are required"}
    ring = _ttl_to_ring(ttl)

    mem = get_memory()
    content = json.dumps({"key": key, "namespace": namespace, "data": data})
    eid = mem.remember(
        agent_id=agent_id,
        entry_type="tool_memory",
        content=content,
        tags=[f"ns:{namespace}", f"key:{key}", "tool_memory"],
        ring=ring,
    )
    return {"success": True, "data": {"memory_id": eid, "stored": True, "ttl": ttl}}


def _cmd_memory_retrieve(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    namespace = args.get("namespace", "default")
    if not key:
        return {"success": False, "error": "key is required"}

    mem = get_memory()
    entries = mem.recall(agent_id=agent_id, tag="tool_memory", rings=[1, 2, 3], limit=TOOL_MEMORY_RECALL_LIMIT)
    for e in entries:
        try:
            payload = json.loads(e.content)
            if payload.get("key") == key and payload.get("namespace") == namespace:
                return {"success": True, "data": {
                    "memory_id": e.id,
                    "data": payload["data"],
                    "created_at": e.timestamp,
                }}
        except (json.JSONDecodeError, KeyError):
            continue
    return {"success": False, "error": f"memory '{key}' not found in namespace '{namespace}'"}


def _cmd_memory_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    namespace = args.get("namespace", "")
    max_results = args.get("max_results", 20)
    if not query:
        return {"success": False, "error": "query is required"}

    mem = get_memory()
    entries = mem.recall(agent_id=agent_id, tag="tool_memory", rings=[1, 2, 3], limit=TOOL_MEMORY_RECALL_LIMIT)
    results = []
    for e in entries:
        try:
            payload = json.loads(e.content)
            if namespace and payload.get("namespace") != namespace:
                continue
            data_str = payload.get("data", "")
            key_str = payload.get("key", "")
            if query.lower() in data_str.lower() or query.lower() in key_str.lower():
                results.append({
                    "memory_id": e.id,
                    "key": payload["key"],
                    "namespace": payload["namespace"],
                    "data_preview": data_str[:100],
                    "created_at": e.timestamp,
                })
        except (json.JSONDecodeError, KeyError):
            continue

    results.sort(key=lambda x: -x["created_at"])
    return {"success": True, "data": {"results": results[:max_results], "count": len(results)}}


def _cmd_memory_forget(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    namespace = args.get("namespace", "")
    if not key and not namespace:
        return {"success": False, "error": "key or namespace is required"}

    mem = get_memory()
    entries = mem.recall(agent_id=agent_id, tag="tool_memory", rings=[1, 2, 3], limit=TOOL_MEMORY_RECALL_LARGE)
    removed = 0
    for e in entries:
        try:
            payload = json.loads(e.content)
            keep = True
            if key and namespace:
                keep = not (payload.get("key") == key and payload.get("namespace") == namespace)
            elif namespace:
                keep = not (payload.get("namespace") == namespace)
            elif key:
                keep = not (payload.get("key") == key)

            # Remove entry by adding with zero importance to trigger eviction
            if not keep:
                mem.remember(
                    agent_id=agent_id, entry_type="tool_memory_deleted",
                    content=e.content, tags=list(e.tags),
                    importance=-1.0, ring=1,
                )
                removed += 1
        except (json.JSONDecodeError, KeyError):
            continue
    return {"success": True, "data": {"removed": removed}}


def _cmd_memory_list(args: dict, agent_id: str) -> dict:
    namespace = args.get("namespace", "")
    max_results = args.get("max_results", 50)

    mem = get_memory()
    entries = mem.recall(agent_id=agent_id, tag="tool_memory", rings=[1, 2, 3], limit=TOOL_MEMORY_RECALL_LIMIT)
    now = time.time()
    items = []
    for e in entries:
        try:
            payload = json.loads(e.content)
            if namespace and payload.get("namespace") != namespace:
                continue
            items.append({
                "memory_id": e.id,
                "key": payload["key"],
                "namespace": payload["namespace"],
                "data_preview": payload.get("data", "")[:80],
                "ttl_remaining": max(0, int(e.ttl - (now - e.timestamp))) if e.ttl else -1,
            })
        except (json.JSONDecodeError, KeyError):
            continue

    items.sort(key=lambda x: -x["ttl_remaining"] if x["ttl_remaining"] >= 0 else 0)
    return {"success": True, "data": {"memories": items[:max_results], "count": len(items)}}


def _cmd_memory_stats(args: dict, agent_id: str) -> dict:
    mem = get_memory()
    stats = mem.stats()
    return {"success": True, "data": {
        "working_entries": stats["working"]["entries"],
        "short_entries": stats["short"]["entries"],
        "long_entries": stats["long"]["entries"],
        "total_tokens": stats["working"]["tokens"] + stats["short"]["tokens"] + stats["long"]["tokens"],
    }}


def _cmd_session_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    limit = args.get("limit", 10)
    if not query:
        return {"success": False, "error": "query is required"}
    mem = get_memory()
    results = mem.search_long_term(query, agent_id=agent_id, limit=limit)
    return {"success": True, "data": {"results": results, "count": len(results)}}


def register_tools() -> None:
    register(ToolSpec(name="memory_store",
                      description="Store a Memory entry (with TTL) into the main MemoryManager",
                      category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("key", "string", required=True),
                                  ParamSpec("data", "string", required=True),
                                  ParamSpec("namespace", "string", default="default"),
                                  ParamSpec("ttl", "int", default=3600)],
                      handler=_cmd_memory_store))
    register(ToolSpec(name="memory_retrieve",
                      description="Retrieve Memory by key",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("key", "string", required=True),
                                  ParamSpec("namespace", "string", default="default")],
                      handler=_cmd_memory_retrieve))
    register(ToolSpec(name="memory_search",
                      description="Search Memory content",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("query", "string", required=True),
                                  ParamSpec("namespace", "string", default=""),
                                  ParamSpec("max_results", "int", default=20)],
                      handler=_cmd_memory_search))
    register(ToolSpec(name="memory_forget",
                      description="Delete Memory entry",
                      category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("key", "string", default=""),
                                  ParamSpec("namespace", "string", default="")],
                      handler=_cmd_memory_forget))
    register(ToolSpec(name="memory_list",
                      description="List all Memory entries",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("namespace", "string", default=""),
                                  ParamSpec("max_results", "int", default=50)],
                      handler=_cmd_memory_list))
    register(ToolSpec(name="memory_stats",
                      description="Memory storage statistics",
                      category="generic", ring=R.RING_1, danger=0,
                      handler=_cmd_memory_stats))
    register(ToolSpec(name="session_search",
                      description="Full-text search across session history Memory (FTS5), supports keywords and phrases",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("query", "string", required=True, description="Search keywords, supports FTS5 syntax"),
                                  ParamSpec("limit", "int", default=10, description="Max results")],
                      handler=_cmd_session_search))
