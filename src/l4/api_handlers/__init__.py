"""API handler mixin — all _* handler methods extracted from api_gateway.py."""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.agent import DEFAULT_CELL_ID

from ..api.api_handlers_cards import (
    card_gate_history,
    card_rollback,
    get_card,
    list_cards,
    sideload_dispatch,
    submit_batch,
    submit_card,
)
from ..api_handlers.api_handlers_agent import (
    agent_direct as _agent_direct,
)
from ..api_handlers.api_handlers_agent import (
    agent_direct_close as _agent_direct_close,
)
from ..api_handlers.api_handlers_agent import (
    agent_list as _agent_list,
)
from ..api_handlers.api_handlers_agent import (
    agent_preconnect as _agent_preconnect,
)
from ..api_handlers.api_handlers_agent import (
    agent_reachable as _agent_reachable,
)
from ..api_handlers.api_handlers_agent import (
    agent_review_message as _agent_review_message,
)
from ..api_handlers.api_handlers_agent import (
    agent_select as _agent_select,
)
from ..api_handlers.api_handlers_agent import (
    agent_select_by as _agent_select_by,
)
from ..api_handlers.api_handlers_cluster import (
    cluster_composites as _cluster_composites,
)
from ..api_handlers.api_handlers_cluster import (
    cluster_expand as _cluster_expand,
)
from ..api_handlers.api_handlers_cluster import (
    cluster_shrink as _cluster_shrink,
)
from ..api_handlers.api_handlers_cluster import (
    cluster_status as _cluster_status,
)
from ..api_handlers.api_handlers_discussion import (
    handle_discussion_answers,
    handle_discussion_get,
    handle_discussion_push_l3a,
    handle_discussion_report,
    handle_discussion_reports,
    handle_discussion_sessions,
    handle_discussion_start,
    handle_discussion_supplement,
)
from ..api_handlers.api_handlers_monitor import (
    comm_recent,
    comm_stats,
    export_counter,
    export_metrics,
    loop_stats,
    loops_recent,
    network_health,
    token_cells,
    token_global,
    token_stats,
)

logger = logging.getLogger(__name__)


class ApiHandlers:
    """Handler methods for API Gateway. Mixed into ApiGateway."""

    # ── Health / System ──

    def _health(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel import health as _health_fn
            return _health_fn()
        except Exception as e:
            return {"status": "FAIL", "error": str(e)}

    # ── Cards ──

    def _list_cards(self, body: dict) -> dict:
        return list_cards(body)

    def _get_card(self, body: dict) -> dict:
        return get_card(body)

    def _submit_card(self, body: dict) -> dict:
        return submit_card(body)

    def _submit_batch(self, body: dict) -> dict:
        try:
            from l3.card.card_registry import get_registry
            cards = body.get("cards", [])
            ids = [get_registry().submit(c.get("intent", ""), c.get("domain", "")) for c in cards]
            return {"success": True, "card_ids": ids, "count": len(ids)}
        except Exception as e:
            return {"error": str(e)}

    def _processes(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel.process import get_table
            return {"processes": get_table().list()}
        except Exception as e:
            return {"error": str(e)}

    def _devices(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel.device import get_device_manager
            return {"devices": get_device_manager().list()}
        except Exception as e:
            return {"error": str(e)}

    def _settings(self, body: dict | None = None) -> dict:
        try:
            from l3.config.settings_center import get_center
            return {"settings": get_center().all()}
        except Exception as e:
            return {"error": str(e)}

    def _set_settings(self, body: dict) -> dict:
        try:
            from l3.config.settings_center import get_center
            return get_center().set_many(body)
        except Exception as e:
            return {"error": str(e)}

    def _syscalls(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel.registry import get_registry
            return {"syscalls": get_registry().syscalls()}
        except Exception as e:
            return {"error": str(e)}

    # ── Agents / Shell ──

    def _agent_list(self, body: dict | None = None) -> dict:
        return _agent_list(body)

    def _agent_select(self, body: dict | None = None) -> dict:
        return _agent_select(body)

    def _agent_select_by(self, body: dict | None = None) -> dict:
        return _agent_select_by(body)

    def _shell_dispatch(self, body: dict | None = None) -> dict:
        from ..api_handlers.api_handlers_agent import _shell_dispatch as _fn
        return _fn(body)

    def _shell_autocomplete(self, body: dict | None = None) -> dict:
        from ..api_handlers.api_handlers_agent import _shell_autocomplete as _fn
        return _fn(body)

    def _shell_commands(self, body: dict | None = None) -> dict:
        from ..api_handlers.api_handlers_agent import _shell_commands as _fn
        return _fn(body)

    def _agent_review_message(self, body: dict | None = None) -> dict:
        return _agent_review_message(body)

    def _agent_preconnect(self, body: dict | None = None) -> dict:
        return _agent_preconnect(body)

    def _agent_reachable(self, body: dict | None = None) -> dict:
        return _agent_reachable(body)

    def _agent_direct(self, body: dict | None = None) -> dict:
        return _agent_direct(body)

    def _agent_direct_close(self, body: dict | None = None) -> dict:
        return _agent_direct_close(body)

    def _network_health(self, body: dict | None = None) -> dict:
        return network_health(body)

    # ── Cells / Cluster ──

    def _cell_liveness(self, body: dict | None = None) -> dict:
        from l1.kernel.params.agent import DEFAULT_CELL_ID as _dcid
        try:
            from l3.cell import get_cell
            cell_id = (body or {}).get("cell_id", _dcid)
            cell = get_cell(cell_id)
            return cell.liveness()
        except Exception as e:
            return {"error": str(e), "overall": "unreachable"}

    def _peers(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel.net import get_net
            return {"peers": get_net().list_peers()}
        except Exception as e:
            return {"peers": [], "error": str(e)}

    def _cell_stop(self, body: dict) -> dict:
        try:
            from l3.cell import get_cell
            cell_id = body.get("cell_id", DEFAULT_CELL_ID)
            cell = get_cell(cell_id)
            return cell.emergency_stop()
        except Exception as e:
            return {"error": str(e)}

    def _cluster_status(self, body: dict | None = None) -> dict:
        return _cluster_status(body)

    def _cluster_composites(self, body: dict | None = None) -> dict:
        return _cluster_composites(body)

    def _cluster_expand(self, body: dict) -> dict:
        return _cluster_expand(body)

    def _cluster_shrink(self, body: dict) -> dict:
        return _cluster_shrink(body)

    def _cellmon_list(self, body: dict | None = None) -> dict:
        from l3.cell.components.cell_monitor import get_cell_monitor
        cm = get_cell_monitor()
        return {"cells": cm.list_cells(), "stats": cm.stats()}

    def _cellmon_get(self, body: dict) -> dict:
        cid = (body or {}).get("_id", "")
        from l3.cell.components.cell_monitor import get_cell_monitor
        cell = get_cell_monitor().get_cell(cid)
        return {"error": f"cell not found: {cid}"} if not cell else {"cell": cell}

    def _cellmon_events(self, body: dict | None = None) -> dict:
        b = body or {}
        from l3.cell.components.cell_monitor import get_cell_monitor
        events = get_cell_monitor().get_events(
            cell_id=b.get("cell_id", ""), since=b.get("since", 0.0), limit=b.get("limit", 50))
        return {"events": events, "count": len(events)}

    def _card_rollback(self, body: dict) -> dict:
        return card_rollback(body)

    def _sideload_dispatch(self, body: dict) -> dict:
        return sideload_dispatch(body)

    # ── MCP Bridge ──

    def _mcp_import(self, body: dict) -> dict:
        try:
            from ..mcp_bridge import McpClient, get_bridge
            server_name = body.get("server_name", "")
            endpoint = body.get("endpoint", "")
            if not server_name or not endpoint:
                return {"error": "server_name and endpoint are required"}
            api_key = body.get("api_key", "")
            client = McpClient(endpoint, api_key)
            return get_bridge().import_server(server_name, client)
        except Exception as e:
            return {"error": str(e)}

    def _mcp_list(self, body: dict | None = None) -> dict:
        try:
            from ..mcp_bridge import get_bridge
            return get_bridge().status()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _mcp_remove(self, body: dict) -> dict:
        try:
            from ..mcp_bridge import get_bridge
            server_name = body.get("server_name", "")
            if not server_name:
                return {"error": "server_name is required"}
            return get_bridge().remove_server(server_name)
        except Exception as e:
            return {"error": str(e)}

    # ── Cron Scheduler ──

    def _cron_list(self, body: dict | None = None) -> dict:
        try:
            from ..cron_scheduler import get_scheduler
            return {"success": True, "schedules": get_scheduler().list()}
        except Exception as e:
            return {"error": str(e)}

    def _cron_add(self, body: dict) -> dict:
        try:
            from ..cron_scheduler import get_scheduler
            entry_id = body.get("id", "")
            cron = body.get("cron", "")
            if not entry_id:
                return {"success": False, "error": "id is required"}
            if not cron:
                return {"success": False, "error": "cron expression is required"}
            return get_scheduler().add(
                entry_id=entry_id, cron=cron,
                intent=body.get("intent", ""), domain=body.get("domain", ""),
                priority=body.get("priority", 5))
        except Exception as e:
            return {"error": str(e)}

    def _cron_remove(self, body: dict) -> dict:
        try:
            from ..cron_scheduler import get_scheduler
            return get_scheduler().remove(body.get("id", ""))
        except Exception as e:
            return {"error": str(e)}

    def _security_check(self, body: dict) -> dict:
        from l3.services.central_security import get_center
        return get_center().check_all(
            action=body.get("action", ""), agent_id=body.get("agent_id", ""),
            target=body.get("target", ""), args=body.get("args", {}),
            tool_name=body.get("tool_name", ""), user_token=body.get("user_token", ""))

    def _security_stats(self, body: dict | None = None) -> dict:
        from l3.services.central_security import get_center
        return get_center().stats()

    def _memory_store(self, body: dict) -> dict:
        from l3.memory.central_memory import get_center
        return get_center().remember(
            agent_id=body.get("agent_id", ""), content=body.get("content", ""),
            entry_type=body.get("entry_type", "observation"), tags=body.get("tags", []),
            ring=body.get("ring", 1), importance=body.get("importance", 0.5))

    def _memory_recall(self, body: dict) -> dict:
        from l3.memory.central_memory import get_center
        results = get_center().recall(
            agent_id=body.get("agent_id", ""), query=body.get("query", ""),
            tags=body.get("tags"), rings=body.get("rings"),
            limit=body.get("limit", 20),
            graph_diffusion=bool(body.get("graph_diffusion", False)))
        return {"success": True, "results": results, "count": len(results)}

    def _memory_stats(self, body: dict | None = None) -> dict:
        from l3.memory.central_memory import get_center
        return {"success": True, "stats": get_center().stats()}

    # ── R5 swarm-domain graph (frontend-switchable) ──

    def _memory_graph_status(self, body: dict | None = None) -> dict:
        """GET /api/memory/graph — graph switch state + stats."""
        from l3.memory.memory_graph import get_graph
        g = get_graph()
        return {
            "success": True,
            "enabled": g.enabled,
            "stats": g.stats(),
            "compact": g.compact_report(min_degree=2),
        }

    def _memory_graph_set(self, body: dict | None = None) -> dict:
        """PUT /api/memory/graph — toggle the graph switch (persisted).

        Body: {"enabled": true|false}
        Persisted via SettingsCenter (memory.graph.enabled → .praxis_settings.json).
        """
        b = body or {}
        if "enabled" not in b:
            return {"success": False, "error": "enabled (bool) is required"}
        flag = bool(b["enabled"])
        try:
            from l3.config.settings_center import get_center as _sc
            _sc().set("memory.graph.enabled", flag)
        except Exception:
            logger.debug("api_handlers: graph enabled persistence failed (best-effort)", exc_info=True)
        from l3.memory.memory_graph import get_graph
        g = get_graph()
        g.set_enabled(flag)
        return {"success": True, "enabled": g.enabled,
                "persisted": "memory.graph.enabled"}

    def _memory_graph_compact(self, body: dict | None = None) -> dict:
        """POST /api/memory/graph/compact — run graph reduction.

        Body: {"dry_run": true|false, "min_degree": 2}
        """
        b = body or {}
        dry = b.get("dry_run", True)
        min_degree = int(b.get("min_degree", 2))
        from l3.memory.memory_graph import get_graph
        return get_graph().compact(min_degree=min_degree, dry_run=bool(dry))

    def _memory_graph_edge(self, body: dict | None = None) -> dict:
        """POST /api/memory/graph/edge — add a semantic edge.

        Body: {"from_id", "to_id", "relation": "contradicts|depends_on|refines",
               "weight": 1.5, "created_by": "llm"}
        """
        b = body or {}
        from l3.memory.memory_graph import get_graph
        return get_graph().add_semantic_edge(
            from_id=b.get("from_id", ""), to_id=b.get("to_id", ""),
            relation=b.get("relation", ""),
            weight=float(b.get("weight", 1.5)),
            created_by=b.get("created_by", "llm"))

    def _memory_graph_semantic(self, body: dict | None = None) -> dict:
        """GET /api/memory/graph/semantic — list semantic edges."""
        from l3.memory.memory_graph import get_graph
        return {"success": True,
                "edges": get_graph().semantic_edges(
                    limit=int((body or {}).get("limit", 50)))}

    # ── Mer symbolic memory (bypass) ──

    def _memory_mer_status(self, body: dict | None = None) -> dict:
        """GET /api/memory/mer — Mer transformer state + stats."""
        from l3.memory.memory_mer import get_mer
        return {"success": True, "mer": get_mer().stats()}

    def _memory_mer_set(self, body: dict | None = None) -> dict:
        """PUT /api/memory/mer — toggle Mer side-channel (persisted)."""
        b = body or {}
        if "enabled" not in b:
            return {"success": False, "error": "enabled (bool) is required"}
        flag = bool(b["enabled"])
        try:
            from l3.config.settings_center import get_center as _sc
            _sc().set("memory.mer.enabled", flag)
        except Exception:
            logger.debug("api_handlers: mer enabled persistence failed (best-effort)", exc_info=True)
        from l3.memory.memory_mer import get_mer
        m = get_mer()
        m.set_enabled(flag)
        return {"success": True, "enabled": m.enabled,
                "persisted": "memory.mer.enabled"}

    def _memory_mer_transform(self, body: dict | None = None) -> dict:
        """POST /api/memory/mer/transform — run one Mer pass (manual)."""
        from l3.memory.memory_mer import get_mer
        return get_mer().transform_and_archive(
            scope_ids=(body or {}).get("scope_ids"))

    def _plugin_list(self, body: dict | None = None) -> dict:
        from l3.services.central_plugin import get_center
        kind = (body or {}).get("kind", "")
        return {"success": True, "plugins": get_center().list_plugins(kind)}

    def _plugin_install_tool(self, body: dict) -> dict:
        from l3.services.central_plugin import get_center
        return get_center().install_tool_plugin(
            name=body.get("name", ""), tools=body.get("tools", []),
            description=body.get("description", ""))

    def _plugin_remove(self, body: dict) -> dict:
        from l3.services.central_plugin import get_center
        return get_center().remove_tool_plugin(body.get("name", ""))

    def _plugin_install_mcp(self, body: dict) -> dict:
        from l3.services.central_plugin import get_center
        return get_center().install_mcp(
            server_name=body.get("server_name", ""), endpoint=body.get("endpoint", ""),
            api_key=body.get("api_key", ""))

    def _plugin_stats(self, body: dict | None = None) -> dict:
        from l3.services.central_plugin import get_center
        return {"success": True, "stats": get_center().stats()}

    def _trust_check(self, body: dict) -> dict:
        from l3.services.content_trust import get_trust
        ct = get_trust(body.get("policy", ""))
        prov = ct.tag(
            source_type=body.get("source_type", "unknown"), source_id=body.get("source_id", ""),
            method=body.get("method", ""), trace_id=body.get("trace_id", ""))
        return {"provenance": prov.to_dict(), "can_recall": ct.can_recall(prov),
                "can_store": ct.can_store(prov)}

    def _trust_stats(self, body: dict | None = None) -> dict:
        from l3.services.content_trust import get_trust
        return {"stats": get_trust().stats()}

    def _session_state(self, body: dict | None = None) -> dict:
        from l2.l2_shell import get_state
        s = get_state()
        return {"mode": s.mode, "agent_id": s.agent_id or "",
                "cell_id": s.cell_id, "is_direct": s.is_direct()}

    def _card_types_list(self, body: dict | None = None) -> dict:
        from l3.card.card_unified import list_card_types
        return {"success": True, "types": list_card_types()}

    def _card_types_register(self, body: dict) -> dict:
        from l3.card.card_unified import register_card_type
        name = body.get("name", "")
        defn = body.get("definition", {})
        if not name or not defn:
            return {"error": "name and definition are required"}
        register_card_type(name, defn)
        return {"success": True, "name": name}

    def _card_unified_submit(self, body: dict) -> dict:
        from l3.card.card_unified import CardSummary, CardUnified
        card = CardUnified(nature=body.get("nature", "execution"), priority=body.get("priority", 5))
        card.summary = CardSummary(
            title=body.get("title", ""), description=body.get("description", ""),
            columns=body.get("columns", {}))
        for pd in body.get("phases", []):
            phase = card.add_phase(
                name=pd.get("name", ""), mode=pd.get("mode", "single"),
                agents=pd.get("agents", []), review_prompt=pd.get("review_prompt", ""))
            for td in pd.get("tasks", []):
                card.add_task(phase_name=phase.name, action=td.get("action", ""),
                              target=td.get("target", ""), params=td.get("params", {}),
                              agent=td.get("agent", ""))
        card.submit()
        return {"success": True, "card": card.to_dict(include_hidden=False)}

    def _card_plan(self, body: dict) -> dict:
        from l3.card.card_registry import get_registry
        card_id = body.get("card_id", "")
        if not card_id:
            return {"error": "card_id required"}
        return get_registry().get_card_plan(card_id)

    def _cache_stats(self, body: dict | None = None) -> dict:
        try:
            from l3.agent_terminal import get_terminals
            seen = {}
            for aid, term in get_terminals().items():
                try:
                    seen[aid] = term.file_cache.stats()
                except Exception as e:
                    logger.warning("cache_stats: %s", e)
            return {"caches": seen, "count": len(seen)}
        except Exception as e:
            return {"error": str(e)}

    def _token_stats(self, body: dict | None = None) -> dict:
        return token_stats(body)

    def _token_cells(self, body: dict | None = None) -> dict:
        return token_cells(body)

    def _token_global(self, body: dict | None = None) -> dict:
        return token_global(body)

    # ── Comm / Tools ──

    def _comm_stats(self, body: dict | None = None) -> dict:
        return comm_stats(body)

    def _comm_recent(self, body: dict | None = None) -> dict:
        return comm_recent(body)

    def _tool_stats(self, body: dict | None = None) -> dict:
        try:
            from l3.services.counter import get_counter
            return get_counter().tool_summary()
        except Exception as e:
            return {"error": str(e)}

    def _tool_policy_set(self, body: dict) -> dict:
        try:
            from l3.tool_system.tool_policy import PolicyAction, PolicyRule, PolicyScope, ToolPolicy
            scope_str = body.get("scope", "global")
            scope_parts = scope_str.split(":", 1)
            scope = PolicyScope(scope_parts[0])
            scope_id = scope_parts[1] if len(scope_parts) > 1 else ""
            rule = PolicyRule(scope=scope, scope_id=scope_id, tool=body.get("tool", "*"),
                              action=PolicyAction(body.get("action", "disable")),
                              reason=body.get("reason", ""))
            ToolPolicy.add(rule)
            return {"success": True, "rule": rule.key()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _tool_policy_list(self, body: dict | None = None) -> dict:
        try:
            from l3.tool_system.tool_policy import ToolPolicy
            return {"success": True, "policies": ToolPolicy.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _tool_policy_remove(self, body: dict) -> dict:
        try:
            from l3.tool_system.tool_policy import PolicyScope, ToolPolicy
            scope_str = body.get("scope", "global")
            scope_parts = scope_str.split(":", 1)
            scope = PolicyScope(scope_parts[0])
            scope_id = scope_parts[1] if len(scope_parts) > 1 else ""
            ok = ToolPolicy.remove(tool=body.get("tool", "*"), scope=scope, scope_id=scope_id)
            return {"success": ok}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _loop_stats(self, body: dict | None = None) -> dict:
        return loop_stats(body)

    def _loops_recent(self, body: dict | None = None) -> dict:
        return loops_recent(body)

    # ── Bootstrap / Export ──

    def _bootstrap_status(self, body: dict | None = None) -> dict:
        try:
            from l3.config.bootstrap import _CONFIG_PATH, needs_bootstrap
            return {"needed": needs_bootstrap(), "config_path": _CONFIG_PATH}
        except Exception as e:
            return {"error": str(e)}

    def _bootstrap_defaults(self, body: dict | None = None) -> dict:
        try:
            from l3.config.bootstrap import get_defaults
            return get_defaults()
        except Exception as e:
            return {"error": str(e)}

    def _bootstrap_apply(self, body: dict) -> dict:
        try:
            from l3.config.bootstrap import apply_config
            return apply_config(body)
        except Exception as e:
            return {"error": str(e)}

    def _export_counter(self, body: dict | None = None) -> dict:
        return export_counter(body)

    def _export_metrics(self, body: dict | None = None) -> dict:
        return export_metrics(body)

    # ── System Lifecycle ──

    def _boot(self, body: dict | None = None) -> dict:
        try:
            from l3.boot.boot import boot
            r = boot()
            return {"success": r.get("success", False), "elapsed": r.get("elapsed", 0),
                    "agents": r.get("agents", []), "steps": r.get("steps", [])}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _shutdown(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel.os import get_os
            osys = get_os()
            r = osys.shutdown()
            return r
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _reboot(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel.os import get_os
            osys = get_os()
            r = osys.restart()
            return {"success": r.get("success", False), "elapsed": r.get("elapsed", 0)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _reload(self, body: dict | None = None) -> dict:
        try:
            from l3.boot.boot import _load_config, _load_constitution, _load_tools
            results = {}
            for name, fn in [("constitution", _load_constitution),
                             ("config", _load_config),
                             ("tools", _load_tools)]:
                try:
                    r = fn()
                    results[name] = "ok" if r.get("success") else r.get("error", "?")
                except Exception as e:
                    results[name] = f"error: {e}"
            return {"success": True, "results": results}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _reset(self, body: dict | None = None) -> dict:
        try:
            from l3.boot.lifecycle import factory_reset
            wipe_config = (body or {}).get("wipe_config", False)
            r = factory_reset(wipe_config=wipe_config)
            return r
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _boot_status(self, body: dict | None = None) -> dict:
        try:
            from l1.kernel.os import get_os
            osys = get_os()
            from l3.boot.boot import boot_status
            r = boot_status()
            r["os"] = osys.status()
            return r
        except Exception as e:
            return {"error": str(e)}

    # ── Credential Vault ──

    def _credential_status(self, body: dict | None = None) -> dict:
        try:
            from ..vault.credential_vault import export_vault_status, list_credentials
            provider = (body or {}).get("provider", "")
            if provider:
                return list_credentials(provider)
            return export_vault_status()
        except Exception as e:
            return {"error": str(e)}

    def _credential_set(self, body: dict) -> dict:
        try:
            from ..vault.credential_vault import set_credential
            provider = body.get("provider", "")
            key = body.get("key", "api_key")
            value = body.get("value", "")
            if not provider or not value:
                return {"error": "provider and value are required"}
            return set_credential(provider, key, value)
        except Exception as e:
            return {"error": str(e)}

    def _credential_delete(self, body: dict) -> dict:
        try:
            from ..vault.credential_vault import delete_credential
            provider = body.get("provider", "")
            key = body.get("key", "")
            if not provider:
                return {"error": "provider is required"}
            return delete_credential(provider, key)
        except Exception as e:
            return {"error": str(e)}

    def _tool_mode_get(self, body: dict | None = None) -> dict:
        from l3.tool_system.tool_mode import get_mode
        return {"mode": get_mode()}

    def _tool_mode_set(self, body: dict) -> dict:
        from l3.tool_system.tool_mode import set_mode
        return set_mode(body.get("mode", "toggle"))

    # ── Harness mode ──

    def _harness_mode_get(self, body: dict | None = None) -> dict:
        from l3.tool_system.harness import harness_status
        return harness_status()

    def _harness_mode_set(self, body: dict) -> dict:
        from l3.tool_system.harness import set_harness_mode
        return set_harness_mode(body.get("mode", ""),
                                confirmed=bool(body.get("confirm_risk")),
                                source="api")

    # ── Approvals / Pending Queue ──

    def _list_approvals(self, body: dict | None = None) -> dict:
        try:
            from l3.card.approval_gate import get_gate
            return {"pending": get_gate().list_pending()}
        except Exception as e:
            return {"error": str(e)}

    def _approval_respond(self, body: dict) -> dict:
        try:
            from l3.card.approval_gate import get_gate
            req_id = body.get("id", "")
            approved = body.get("approved", False)
            response = body.get("response", "")
            return get_gate().respond(req_id, approved, response)
        except Exception as e:
            return {"error": str(e)}

    def _rollback_context(self, body: dict | None = None) -> dict:
        try:
            from l3.cell import get_cell
            cell_id = (body or {}).get("cell_id", DEFAULT_CELL_ID)
            cell = get_cell(cell_id)
            ring = cell._rollback_ring
            return {"ring_size": len(ring), "max_size": 20,
                    "recent": ring.all()[-5:] if ring.all() else [],
                    "snapshot_count": len(cell._card_snapshots)}
        except Exception as e:
            return {"error": str(e)}

    # ── Card Gate ──

    def _card_gate_config(self, body: dict | None = None) -> dict:
        try:
            from l3.card.card_gate import stats as _gate_stats
            return _gate_stats()
        except Exception as e:
            return {"error": str(e)}

    def _card_gate_config_set(self, body: dict) -> dict:
        try:
            from l3.card.card_gate import get_gate
            gate = get_gate()
            gate.load_config(body)
            return {"success": True, "applied": list(body.keys())}
        except Exception as e:
            return {"error": str(e)}

    def _card_gate_history(self, body: dict | None = None) -> dict:
        try:
            from l3.card.card_gate import list_history
            limit = int((body or {}).get("limit", 50))
            return {"history": list_history(limit), "count": limit}
        except Exception as e:
            return {"error": str(e)}

    def _pending_list(self, body: dict | None = None) -> dict:
        try:
            from l3.card.pending_queue import get_queue
            status = (body or {}).get("status", "PENDING")
            limit = int((body or {}).get("limit", 50))
            return {"pending": get_queue().list(status=status, limit=limit)}
        except Exception as e:
            return {"error": str(e)}

    def _pending_approve(self, body: dict) -> dict:
        try:
            from l3.card.pending_queue import get_queue
            mid = body.get("id", "")
            if not mid:
                return {"error": "id is required"}
            return get_queue().approve(mid, body.get("response", ""))
        except Exception as e:
            return {"error": str(e)}

    def _pending_reject(self, body: dict) -> dict:
        try:
            from l3.card.pending_queue import get_queue
            mid = body.get("id", "")
            if not mid:
                return {"error": "id is required"}
            return get_queue().reject(mid, body.get("response", ""))
        except Exception as e:
            return {"error": str(e)}

    def _pending_escalate(self, body: dict) -> dict:
        try:
            from l3.card.pending_queue import get_queue
            mid = body.get("id", "")
            if not mid:
                return {"error": "id is required"}
            return get_queue().escalate(mid)
        except Exception as e:
            return {"error": str(e)}

    def _pending_priority(self, body: dict) -> dict:
        try:
            from l3.card.pending_queue import get_queue
            mid = body.get("id", "")
            priority = int(body.get("priority", 5))
            if not mid:
                return {"error": "id is required"}
            return get_queue().set_priority(mid, priority)
        except Exception as e:
            return {"error": str(e)}

    def _pending_stats(self, body: dict | None = None) -> dict:
        try:
            from l3.card.pending_queue import get_queue
            return get_queue().stats()
        except Exception as e:
            return {"error": str(e)}

    def _card_gate_stats(self, body: dict | None = None) -> dict:
        try:
            from l3.card.card_gate import stats as _gate_stats
            return _gate_stats()
        except Exception as e:
            return {"error": str(e)}

    def _card_approval_trail(self, body: dict) -> dict:
        try:
            from l3.card.card_registry import get_registry
            card_id = body.get("_id", "")
            card = get_registry().get(card_id)
            if not card:
                return {"error": f"card not found: {card_id}"}
            return {"card_id": card_id, "approval": {
                "status": card.approval_status, "size": card.approval_size,
                "at": card.approval_at, "by": card.approval_by}}
        except Exception as e:
            return {"error": str(e)}

    def _gate_pending(self, body: dict | None = None) -> dict:
        try:
            from l3.card.card_gate import list_pending
            pending = list_pending()
            return {"pending": pending, "count": len(pending)}
        except Exception as e:
            return {"error": str(e)}

    def _gate_respond(self, body: dict) -> dict:
        try:
            from l3.card.card_gate import approve
            card_id = body.get("card_id", "")
            if not card_id:
                return {"error": "card_id is required"}
            decision = bool(body.get("approve", True))
            response = body.get("response", "")
            return approve(card_id, decision, response)
        except Exception as e:
            return {"error": str(e)}

    # ── Routes / V1 API ──

    def _list_endpoints(self, body: dict | None = None) -> dict:
        lines = []
        for r in self._routes:
            display = r.path + "<id>" if r.path.endswith("/") else r.path
            lines.append(f"{r.method:4s} {display:30s}  {r.description}")
        result: dict = {"endpoints": lines}
        # centralized manifest summary (see l4/api/api_endpoints.py)
        try:
            from l4.api.api_endpoints import summary, validate
            result["manifest"] = summary()
            result["manifest_ok"] = validate()["ok"]
        except Exception:
            logger.debug("api_handlers: manifest summary failed, omitted", exc_info=True)
        return result

    def _endpoints(self) -> list[str]:
        return self._list_endpoints().get("endpoints", [])

    def _list_tools_v1(self, body: dict | None = None) -> dict:
        try:
            from l3.tool_system.tool_spec import list_tools
            locale = (body or {}).get("locale", "") if body else ""
            tools = list_tools(locale=locale)
            return {"success": True, "data": [{
                "name": t.name, "description": t.description, "category": t.category,
                "ring": t.ring, "danger": t.danger,
                "parameters": [{"name": p.name, "type": p.type,
                                "required": p.required, "description": p.description}
                               for p in t.parameters],
            } for t in tools], "count": len(tools), "locale": locale or "en"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _list_locales(self, body: dict | None = None) -> dict:
        try:
            from l2.i18n import get_available_locales, get_locale
            return {"success": True, "locales": get_available_locales(), "current": get_locale()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Loop Control ──

    def _loop_config_get(self, body: dict | None = None) -> dict:
        try:
            from l3.config.settings_center import get_center
            center = get_center()
            keys = [
                "loop.max_steps", "loop.timeout", "loop.max_iterations", "loop.max_attempts",
                "loop.continuation_nudge", "loop.tool_repeat_warn", "loop.tool_repeat_stop",
                "loop.coarse_repeat_nudge", "loop.coarse_repeat_stop", "loop.verify_cadence",
            ]
            return {"success": True, "config": {k: center.get(k) for k in keys}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _loop_config_set(self, body: dict) -> dict:
        try:
            from l3.config.settings_center import get_center
            center = get_center()
            config = body or {}
            applied = []
            for key in config:
                center.set(f"loop.{key}", config[key])
                applied.append(key)
            return {"success": True, "applied": applied}
        except Exception as e:
            return {"success": False, "error": str(e)}
