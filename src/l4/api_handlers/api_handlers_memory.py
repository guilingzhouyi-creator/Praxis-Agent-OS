"""API handler mixin — memory, memory-graph and Mer side-channel handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def memory_store(body: dict) -> dict:
    """Store an observation into central memory."""
    from l3.memory.central_memory import get_center

    return get_center().remember(
        agent_id=body.get("agent_id", ""),
        content=body.get("content", ""),
        entry_type=body.get("entry_type", "observation"),
        tags=body.get("tags", []),
        ring=body.get("ring", 1),
        importance=body.get("importance", 0.5),
    )


def memory_recall(body: dict) -> dict:
    """Recall memories by query / tags / rings."""
    from l3.memory.central_memory import get_center

    results = get_center().recall(
        agent_id=body.get("agent_id", ""),
        query=body.get("query", ""),
        tags=body.get("tags"),
        rings=body.get("rings"),
        limit=body.get("limit", 20),
        graph_diffusion=bool(body.get("graph_diffusion", False)),
    )
    return {"success": True, "results": results, "count": len(results)}


def memory_stats(body: dict | None = None) -> dict:
    """Central memory statistics."""
    from l3.memory.central_memory import get_center

    return {"success": True, "stats": get_center().stats()}


def memory_graph_status(body: dict | None = None) -> dict:
    """Graph switch state + stats (GET /api/memory/graph)."""
    from l3.memory.memory_graph import get_graph

    g = get_graph()
    return {
        "success": True,
        "enabled": g.enabled,
        "edge_mode": g.edge_mode,
        "stats": g.stats(),
        "compact": g.compact_report(min_degree=2),
    }


def memory_graph_set(body: dict | None = None) -> dict:
    """Toggle graph switch and/or semantic-extraction mode (PUT /api/memory/graph).

    Body: {"enabled": true|false} and/or {"edge_mode": "off"|"rules"|"hybrid"}
    Persisted via SettingsCenter (memory.graph.* → .praxis_settings.json).
    Edge-mode transitions follow the MemoryGraph state machine.
    """
    b = body or {}
    if "enabled" not in b and "edge_mode" not in b:
        return {"success": False, "error": "enabled (bool) or edge_mode (off|rules|hybrid) is required"}
    from l3.memory.memory_graph import get_graph

    g = get_graph()
    changed: list[str] = []
    if "enabled" in b:
        flag = bool(b["enabled"])
        try:
            from l3.config.settings_center import get_center as _sc

            _sc().set("memory.graph.enabled", flag)
        except Exception:
            logger.debug("memory_graph_set: graph enabled persistence failed (best-effort)", exc_info=True)
        g.set_enabled(flag)
        changed.append("memory.graph.enabled")
    if "edge_mode" in b:
        mode = str(b["edge_mode"]).strip().lower()
        r = g.set_edge_mode(mode)
        if not r.get("success"):
            return {"success": False, "error": r.get("error")}
        try:
            from l3.config.settings_center import get_center as _sc

            _sc().set("memory.graph.edge_mode", mode)
        except Exception:
            logger.debug("memory_graph_set: graph edge_mode persistence failed (best-effort)", exc_info=True)
        changed.append("memory.graph.edge_mode")
    return {"success": True, "enabled": g.enabled, "edge_mode": g.edge_mode, "persisted": changed}


def memory_graph_compact(body: dict | None = None) -> dict:
    """Run graph reduction (POST /api/memory/graph/compact).

    Body: {"dry_run": true|false, "min_degree": 2}
    """
    b = body or {}
    dry = b.get("dry_run", True)
    min_degree = int(b.get("min_degree", 2))
    from l3.memory.memory_graph import get_graph

    return get_graph().compact(min_degree=min_degree, dry_run=bool(dry))


def memory_graph_edge(body: dict | None = None) -> dict:
    """Add a semantic edge (POST /api/memory/graph/edge).

    Body: {"from_id", "to_id", "relation": "contradicts|depends_on|refines",
           "weight": 1.5, "created_by": "llm"}
    """
    b = body or {}
    from l3.memory.memory_graph import get_graph

    return get_graph().add_semantic_edge(
        from_id=b.get("from_id", ""),
        to_id=b.get("to_id", ""),
        relation=b.get("relation", ""),
        weight=float(b.get("weight", 1.5)),
        created_by=b.get("created_by", "llm"),
    )


def memory_graph_semantic(body: dict | None = None) -> dict:
    """List semantic edges (GET /api/memory/graph/semantic)."""
    from l3.memory.memory_graph import get_graph

    return {"success": True, "edges": get_graph().semantic_edges(limit=int((body or {}).get("limit", 50)))}


def memory_mer_status(body: dict | None = None) -> dict:
    """Mer transformer state + stats (GET /api/memory/mer)."""
    from l3.memory.memory_mer import get_mer

    return {"success": True, "mer": get_mer().stats()}


def memory_mer_set(body: dict | None = None) -> dict:
    """Toggle Mer side-channel, persisted (PUT /api/memory/mer)."""
    b = body or {}
    if "enabled" not in b:
        return {"success": False, "error": "enabled (bool) is required"}
    flag = bool(b["enabled"])
    try:
        from l3.config.settings_center import get_center as _sc

        _sc().set("memory.mer.enabled", flag)
    except Exception:
        logger.debug("memory_mer_set: mer enabled persistence failed (best-effort)", exc_info=True)
    from l3.memory.memory_mer import get_mer

    m = get_mer()
    m.set_enabled(flag)
    return {"success": True, "enabled": m.enabled, "persisted": "memory.mer.enabled"}


def memory_mer_transform(body: dict | None = None) -> dict:
    """Run one Mer pass manually (POST /api/memory/mer/transform)."""
    from l3.memory.memory_mer import get_mer

    return get_mer().transform_and_archive(scope_ids=(body or {}).get("scope_ids"))
