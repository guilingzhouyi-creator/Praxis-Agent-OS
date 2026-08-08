"""API handler mixin — delegation aggregator for all ``_*`` handler methods.

Every handler's implementation lives in a domain submodule under
``l4/api_handlers/``; this class keeps the exact method names/signatures the
route table resolves (``".method_name"`` in ``api_routes.py``) and delegates.
"""

from __future__ import annotations

from typing import Any  # noqa: F401 — type re-export

from ..api.api_handlers_cards import (  # noqa: F401 — mixin re-exports
    card_gate_history as cards_card_gate_history,
)
from ..api.api_handlers_cards import (
    card_rollback,
    get_card,
    list_cards,
    sideload_dispatch,
    submit_card,
)

# ── Domain submodules ──
from ..api_handlers.api_handlers_agent import (
    agent_direct,
    agent_direct_close,
    agent_list,
    agent_preconnect,
    agent_reachable,
    agent_review_message,
    agent_select,
    agent_select_by,
)
from ..api_handlers.api_handlers_cardtypes import (
    card_plan,
    card_types_list,
    card_types_register,
    card_unified_submit,
    submit_batch_preserving,
)
from ..api_handlers.api_handlers_cells import (
    cell_liveness,
    cell_stop,
    cellmon_events,
    cellmon_get,
    cellmon_list,
    list_peers,
    rollback_context,
)
from ..api_handlers.api_handlers_cluster import (
    cluster_composites,
    cluster_expand,
    cluster_shrink,
    cluster_status,
)
from ..api_handlers.api_handlers_credentials import credential_delete, credential_set, credential_status
from ..api_handlers.api_handlers_cron import cron_add, cron_list, cron_remove
from ..api_handlers.api_handlers_endpoints import endpoints_only, list_endpoints, list_locales, list_tools_v1
from ..api_handlers.api_handlers_gates import (
    approval_respond,
    card_approval_trail,
    card_gate_config,
    card_gate_config_set,
    card_gate_history,
    card_gate_stats,
    gate_pending,
    gate_respond,
    list_approvals,
    pending_approve,
    pending_escalate,
    pending_list,
    pending_priority,
    pending_reject,
    pending_stats,
)
from ..api_handlers.api_handlers_loop import loop_auto_test_get, loop_auto_test_set, loop_config_get, loop_config_set
from ..api_handlers.api_handlers_mcpbridge import mcp_import, mcp_list, mcp_remove
from ..api_handlers.api_handlers_memory import (
    memory_graph_compact,
    memory_graph_edge,
    memory_graph_semantic,
    memory_graph_set,
    memory_graph_status,
    memory_mer_set,
    memory_mer_status,
    memory_mer_transform,
    memory_recall,
    memory_stats,
    memory_store,
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
from ..api_handlers.api_handlers_plugins import (
    plugin_install_mcp,
    plugin_install_tool,
    plugin_list,
    plugin_remove,
    plugin_stats,
    trust_check,
    trust_stats,
)
from ..api_handlers.api_handlers_security import (
    harness_mode_get,
    harness_mode_set,
    security_check,
    security_mode_get,
    security_mode_notifications,
    security_mode_set,
    security_stats,
    tool_mode_get,
    tool_mode_set,
)
from ..api_handlers.api_handlers_session import session_state
from ..api_handlers.api_handlers_system import (
    bootstrap_apply,
    bootstrap_defaults,
    bootstrap_status,
    list_devices,
    list_processes,
    list_syscalls,
    retriever_backend_get,
    retriever_backend_set,
    settings_all,
    settings_set_many,
    system_boot,
    system_boot_status,
    system_health,
    system_reboot,
    system_reload,
    system_reset,
    system_shutdown,
)
from ..api_handlers.api_handlers_tools import (
    cache_stats,
    tool_policy_list,
    tool_policy_remove,
    tool_policy_set,
    tool_stats,
)


class ApiHandlers:
    """Handler methods for API Gateway. Mixed into ApiGateway.

    All methods delegate to domain submodules; only the method surface (names
    and signatures) lives here so ``api_routes.py`` ``".method_name"`` refs
    keep resolving unchanged.
    """

    # ── Injected by ApiGateway (see api_gateway.py) ──
    _routes: list[Any]

    # ── Health / System ──

    def _health(self, body: dict | None = None) -> dict:
        return system_health(body)

    # ── Cards ──

    def _list_cards(self, body: dict) -> dict:
        return list_cards(body)

    def _get_card(self, body: dict) -> dict:
        return get_card(body)

    def _submit_card(self, body: dict) -> dict:
        return submit_card(body)

    def _submit_batch(self, body: dict) -> dict:
        return submit_batch_preserving(body)

    def _processes(self, body: dict | None = None) -> dict:
        return list_processes(body)

    def _devices(self, body: dict | None = None) -> dict:
        return list_devices(body)

    def _settings(self, body: dict | None = None) -> dict:
        return settings_all(body)

    def _set_settings(self, body: dict) -> dict:
        return settings_set_many(body)

    def _syscalls(self, body: dict | None = None) -> dict:
        return list_syscalls(body)

    # ── Agents / Shell ──

    def _agent_list(self, body: dict | None = None) -> dict:
        return agent_list(body)

    def _agent_select(self, body: dict | None = None) -> dict:
        return agent_select(body)

    def _agent_select_by(self, body: dict | None = None) -> dict:
        return agent_select_by(body)

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
        return agent_review_message(body)

    def _agent_preconnect(self, body: dict | None = None) -> dict:
        return agent_preconnect(body)

    def _agent_reachable(self, body: dict | None = None) -> dict:
        return agent_reachable(body)

    def _agent_direct(self, body: dict | None = None) -> dict:
        return agent_direct(body)

    def _agent_direct_close(self, body: dict | None = None) -> dict:
        return agent_direct_close(body)

    def _network_health(self, body: dict | None = None) -> dict:
        return network_health(body)

    # ── Cells / Cluster ──

    def _cell_liveness(self, body: dict | None = None) -> dict:
        return cell_liveness(body)

    def _peers(self, body: dict | None = None) -> dict:
        return list_peers(body)

    def _cell_stop(self, body: dict) -> dict:
        return cell_stop(body)

    def _cluster_status(self, body: dict | None = None) -> dict:
        return cluster_status(body)

    def _cluster_composites(self, body: dict | None = None) -> dict:
        return cluster_composites(body)

    def _cluster_expand(self, body: dict) -> dict:
        return cluster_expand(body)

    def _cluster_shrink(self, body: dict) -> dict:
        return cluster_shrink(body)

    def _cellmon_list(self, body: dict | None = None) -> dict:
        return cellmon_list(body)

    def _cellmon_get(self, body: dict) -> dict:
        return cellmon_get(body)

    def _cellmon_events(self, body: dict | None = None) -> dict:
        return cellmon_events(body)

    def _card_rollback(self, body: dict) -> dict:
        return card_rollback(body)

    def _sideload_dispatch(self, body: dict) -> dict:
        return sideload_dispatch(body)

    # ── MCP Bridge ──

    def _mcp_import(self, body: dict) -> dict:
        return mcp_import(body)

    def _mcp_list(self, body: dict | None = None) -> dict:
        return mcp_list(body)

    def _mcp_remove(self, body: dict) -> dict:
        return mcp_remove(body)

    # ── Cron Scheduler ──

    def _cron_list(self, body: dict | None = None) -> dict:
        return cron_list(body)

    def _cron_add(self, body: dict) -> dict:
        return cron_add(body)

    def _cron_remove(self, body: dict) -> dict:
        return cron_remove(body)

    def _security_check(self, body: dict) -> dict:
        return security_check(body)

    def _security_stats(self, body: dict | None = None) -> dict:
        return security_stats(body)

    def _memory_store(self, body: dict) -> dict:
        return memory_store(body)

    def _memory_recall(self, body: dict) -> dict:
        return memory_recall(body)

    def _memory_stats(self, body: dict | None = None) -> dict:
        return memory_stats(body)

    # ── R5 swarm-domain graph (frontend-switchable) ──

    def _memory_graph_status(self, body: dict | None = None) -> dict:
        """GET /api/memory/graph — graph switch state + stats."""
        return memory_graph_status(body)

    def _memory_graph_set(self, body: dict | None = None) -> dict:
        """PUT /api/memory/graph — toggle graph switch and/or semantic-extraction mode."""
        return memory_graph_set(body)

    def _memory_graph_compact(self, body: dict | None = None) -> dict:
        """POST /api/memory/graph/compact — run graph reduction."""
        return memory_graph_compact(body)

    def _memory_graph_edge(self, body: dict | None = None) -> dict:
        """POST /api/memory/graph/edge — add a semantic edge."""
        return memory_graph_edge(body)

    def _memory_graph_semantic(self, body: dict | None = None) -> dict:
        """GET /api/memory/graph/semantic — list semantic edges."""
        return memory_graph_semantic(body)

    # ── Mer symbolic memory (bypass) ──

    def _memory_mer_status(self, body: dict | None = None) -> dict:
        """GET /api/memory/mer — Mer transformer state + stats."""
        return memory_mer_status(body)

    def _memory_mer_set(self, body: dict | None = None) -> dict:
        """PUT /api/memory/mer — toggle Mer side-channel (persisted)."""
        return memory_mer_set(body)

    def _memory_mer_transform(self, body: dict | None = None) -> dict:
        """POST /api/memory/mer/transform — run one Mer pass (manual)."""
        return memory_mer_transform(body)

    def _plugin_list(self, body: dict | None = None) -> dict:
        return plugin_list(body)

    def _plugin_install_tool(self, body: dict) -> dict:
        return plugin_install_tool(body)

    def _plugin_remove(self, body: dict) -> dict:
        return plugin_remove(body)

    def _plugin_install_mcp(self, body: dict) -> dict:
        return plugin_install_mcp(body)

    def _plugin_stats(self, body: dict | None = None) -> dict:
        return plugin_stats(body)

    def _trust_check(self, body: dict) -> dict:
        return trust_check(body)

    def _trust_stats(self, body: dict | None = None) -> dict:
        return trust_stats(body)

    def _session_state(self, body: dict | None = None) -> dict:
        return session_state(body)

    def _card_types_list(self, body: dict | None = None) -> dict:
        return card_types_list(body)

    def _card_types_register(self, body: dict) -> dict:
        return card_types_register(body)

    def _card_unified_submit(self, body: dict) -> dict:
        return card_unified_submit(body)

    def _card_plan(self, body: dict) -> dict:
        return card_plan(body)

    def _cache_stats(self, body: dict | None = None) -> dict:
        return cache_stats(body)

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
        return tool_stats(body)

    def _tool_policy_set(self, body: dict) -> dict:
        return tool_policy_set(body)

    def _tool_policy_list(self, body: dict | None = None) -> dict:
        return tool_policy_list(body)

    def _tool_policy_remove(self, body: dict) -> dict:
        return tool_policy_remove(body)

    def _loop_stats(self, body: dict | None = None) -> dict:
        return loop_stats(body)

    def _loops_recent(self, body: dict | None = None) -> dict:
        return loops_recent(body)

    def _loop_auto_test_get(self, body: dict | None = None) -> dict:
        """GET /api/v2/loop/auto-test — AutoTestGate state + pending feedback."""
        return loop_auto_test_get(body)

    def _loop_auto_test_set(self, body: dict) -> dict:
        """PUT /api/v2/loop/auto-test — switch AutoTestGate mode (off|async)."""
        return loop_auto_test_set(body)

    # ── Bootstrap / Export ──

    def _bootstrap_status(self, body: dict | None = None) -> dict:
        return bootstrap_status(body)

    def _bootstrap_defaults(self, body: dict | None = None) -> dict:
        return bootstrap_defaults(body)

    def _bootstrap_apply(self, body: dict) -> dict:
        return bootstrap_apply(body)

    def _export_counter(self, body: dict | None = None) -> dict:
        return export_counter(body)

    def _export_metrics(self, body: dict | None = None) -> dict:
        return export_metrics(body)

    # ── System Lifecycle ──

    def _boot(self, body: dict | None = None) -> dict:
        return system_boot(body)

    def _shutdown(self, body: dict | None = None) -> dict:
        return system_shutdown(body)

    def _reboot(self, body: dict | None = None) -> dict:
        return system_reboot(body)

    def _reload(self, body: dict | None = None) -> dict:
        return system_reload(body)

    def _reset(self, body: dict | None = None) -> dict:
        return system_reset(body)

    def _boot_status(self, body: dict | None = None) -> dict:
        return system_boot_status(body)

    # ── Credential Vault ──

    def _credential_status(self, body: dict | None = None) -> dict:
        return credential_status(body)

    def _credential_set(self, body: dict) -> dict:
        return credential_set(body)

    def _credential_delete(self, body: dict) -> dict:
        return credential_delete(body)

    def _tool_mode_get(self, body: dict | None = None) -> dict:
        return tool_mode_get(body)

    def _tool_mode_set(self, body: dict) -> dict:
        return tool_mode_set(body)

    # ── Harness mode ──

    def _harness_mode_get(self, body: dict | None = None) -> dict:
        return harness_mode_get(body)

    def _harness_mode_set(self, body: dict) -> dict:
        return harness_mode_set(body)

    # ── Security mode (system posture: productive | security-test) ──

    def _security_mode_get(self, body: dict | None = None) -> dict:
        return security_mode_get(body)

    def _security_mode_set(self, body: dict) -> dict:
        return security_mode_set(body)

    def _security_mode_notifications(self, body: dict | None = None) -> dict:
        """GET /api/v2/security/mode/notifications — recent bypass-detection
        warnings and mode changes for frontend notification (pull channel)."""
        return security_mode_notifications(body)

    # ── Skill retriever backend ──

    def _retriever_backend_get(self, body: dict | None = None) -> dict:
        return retriever_backend_get(body)

    def _retriever_backend_set(self, body: dict) -> dict:
        return retriever_backend_set(body)

    # ── Approvals / Pending Queue ──

    def _list_approvals(self, body: dict | None = None) -> dict:
        return list_approvals(body)

    def _approval_respond(self, body: dict) -> dict:
        return approval_respond(body)

    def _rollback_context(self, body: dict | None = None) -> dict:
        return rollback_context(body)

    # ── Card Gate ──

    def _card_gate_config(self, body: dict | None = None) -> dict:
        return card_gate_config(body)

    def _card_gate_config_set(self, body: dict) -> dict:
        return card_gate_config_set(body)

    def _card_gate_history(self, body: dict | None = None) -> dict:
        return card_gate_history(body)

    def _pending_list(self, body: dict | None = None) -> dict:
        return pending_list(body)

    def _pending_approve(self, body: dict) -> dict:
        return pending_approve(body)

    def _pending_reject(self, body: dict) -> dict:
        return pending_reject(body)

    def _pending_escalate(self, body: dict) -> dict:
        return pending_escalate(body)

    def _pending_priority(self, body: dict) -> dict:
        return pending_priority(body)

    def _pending_stats(self, body: dict | None = None) -> dict:
        return pending_stats(body)

    def _card_gate_stats(self, body: dict | None = None) -> dict:
        return card_gate_stats(body)

    def _card_approval_trail(self, body: dict) -> dict:
        return card_approval_trail(body)

    def _gate_pending(self, body: dict | None = None) -> dict:
        return gate_pending(body)

    def _gate_respond(self, body: dict) -> dict:
        return gate_respond(body)

    # ── Routes / V1 API ──

    def _list_endpoints(self, body: dict | None = None) -> dict:
        return list_endpoints(self._routes)

    def _endpoints(self) -> list[str]:
        return endpoints_only(self._routes)

    def _list_tools_v1(self, body: dict | None = None) -> dict:
        return list_tools_v1(body)

    def _list_locales(self, body: dict | None = None) -> dict:
        return list_locales(body)

    # ── Loop Control ──

    def _loop_config_get(self, body: dict | None = None) -> dict:
        return loop_config_get(body)

    def _loop_config_set(self, body: dict) -> dict:
        return loop_config_set(body)
