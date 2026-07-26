"""Memory tool handlers."""

try:
    from l3.memory import get_memory
    HAS_MEMORY = True
except ImportError:
    HAS_MEMORY = False


def memory_store(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    content = args.get("content", "")
    if not key or not content:
        return {"success": False, "error": "key and content are required"}
    if not HAS_MEMORY:
        return {"success": False, "error": "memory not available"}
    try:
        mem = get_memory()
        mem.remember(agent_id=agent_id, key=key, content=content, entry_type="tool")
        return {"success": True, "key": key}
    except Exception as e:
        return {"success": False, "error": str(e)}


def memory_retrieve(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    if not key:
        return {"success": False, "error": "key is required"}
    if not HAS_MEMORY:
        return {"success": False, "error": "memory not available"}
    try:
        mem = get_memory()
        result = mem.recall(agent_id=agent_id, key=key)
        return {"success": True, "key": key, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def memory_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "query is required"}
    if not HAS_MEMORY:
        return {"success": False, "error": "memory not available"}
    try:
        mem = get_memory()
        results = mem.recall(agent_id=agent_id, query=query)
        return {"success": True, "results": results[:20], "total": len(results) if isinstance(results, list) else 0}
    except Exception as e:
        return {"success": False, "error": str(e)}
