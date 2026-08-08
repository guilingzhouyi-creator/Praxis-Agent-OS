"""API handler mixin — plugin management and content-trust handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def plugin_list(body: dict | None = None) -> dict:
    """List installed plugins by kind."""
    from l3.services.central_plugin import get_center

    kind = (body or {}).get("kind", "")
    return {"success": True, "plugins": get_center().list_plugins(kind)}


def plugin_install_tool(body: dict) -> dict:
    """Install a tool plugin."""
    from l3.services.central_plugin import get_center

    return get_center().install_tool_plugin(
        name=body.get("name", ""), tools=body.get("tools", []), description=body.get("description", "")
    )


def plugin_remove(body: dict) -> dict:
    """Remove a tool plugin."""
    from l3.services.central_plugin import get_center

    return get_center().remove_tool_plugin(body.get("name", ""))


def plugin_install_mcp(body: dict) -> dict:
    """Install an MCP plugin."""
    from l3.services.central_plugin import get_center

    return get_center().install_mcp(
        server_name=body.get("server_name", ""), endpoint=body.get("endpoint", ""), api_key=body.get("api_key", "")
    )


def plugin_stats(body: dict | None = None) -> dict:
    """Plugin center statistics."""
    from l3.services.central_plugin import get_center

    return {"success": True, "stats": get_center().stats()}


def trust_check(body: dict) -> dict:
    """Content-trust provenance check for a source."""
    from l3.services.content_trust import get_trust

    ct = get_trust(body.get("policy", ""))
    prov = ct.tag(
        source_type=body.get("source_type", "unknown"),
        source_id=body.get("source_id", ""),
        method=body.get("method", ""),
        trace_id=body.get("trace_id", ""),
    )
    return {"provenance": prov.to_dict(), "can_recall": ct.can_recall(prov), "can_store": ct.can_store(prov)}


def trust_stats(body: dict | None = None) -> dict:
    """Content-trust statistics."""
    from l3.services.content_trust import get_trust

    return {"stats": get_trust().stats()}
