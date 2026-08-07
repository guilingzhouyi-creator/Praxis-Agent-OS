"""API route registry — single source of truth for all routes.

Each route: (method, path, handler_ref, description)
  handler_ref: "module.function" for standalone functions
               ".method_name" for ApiHandlers mixin methods (resolved via getattr)

Unified prefix convention (P2 migration):
  - Every path is under ``/api/v2/`` (versioned; v1/legacy paths removed).
  - Path segments use kebab-case; ``{param}`` placeholders for path variables.
  - Placeholder names mirror the handler keyword args (e.g. ``{name}`` →
    ``handle_skills_get(body, name="")``), NOT a generic ``id``.
  - Classification/grouping lives in api_endpoints.py (_DOMAIN_GROUP /
    _DOMAIN_BY_PREFIX); validate() enforces these naming rules.
"""

# ── ApiHandlers mixin methods (prefixed with .) ──
# Resolved at runtime via getattr(api_gateway_instance, method_name)

API_ROUTES: list[tuple[str, str, str, str]] = [
    # Core system
    ("GET", "/api/v2/health", ".health", "Kernel health"),
    ("GET", "/api/v2/processes", ".processes", "List processes"),
    ("GET", "/api/v2/devices", ".devices", "List devices"),
    ("GET", "/api/v2/peers", ".peers", "List peers"),
    ("GET", "/api/v2/syscalls", ".syscalls", "List syscalls"),
    ("GET", "/api/v2/endpoints", ".list_endpoints", "List endpoints"),
    ("GET", "/api/v2/mode", ".tool_mode_get", "Get tool mode"),
    ("PUT", "/api/v2/mode", ".tool_mode_set", "Set tool mode"),
    # Harness mode (governed / semi / minimal gate matrix)
    ("GET", "/api/v2/harness/mode", ".harness_mode_get", "Get harness mode"),
    ("POST", "/api/v2/harness/mode", ".harness_mode_set", "Switch harness mode (minimal needs confirm_risk=true)"),
    # System security posture (productive | security-test; attack needs confirm_risk)
    ("GET", "/api/v2/security/mode", ".security_mode_get", "Get system security posture"),
    (
        "POST",
        "/api/v2/security/mode",
        ".security_mode_set",
        "Switch security posture (security-test needs confirm_risk=true)",
    ),
    (
        "GET",
        "/api/v2/security/mode/notifications",
        ".security_mode_notifications",
        "Recent bypass-detection warnings / mode changes (frontend notification)",
    ),
    # Skill retriever backend (tfidf / embedding)
    ("GET", "/api/v2/skills/retriever", ".retriever_backend_get", "Get active skill retriever backend"),
    ("POST", "/api/v2/skills/retriever", ".retriever_backend_set", "Switch skill retriever backend (tfidf|embedding)"),
    # Skill distillation / DPO policy (master switches)
    (
        "GET",
        "/api/v2/skills/distill-policy",
        "l4.api_handlers.api_handlers_skills.handle_skills_distill_policy_get",
        "Skill distillation/DPO policy",
    ),
    (
        "POST",
        "/api/v2/skills/distill-policy",
        "l4.api_handlers.api_handlers_skills.handle_skills_distill_policy_set",
        "Update skill distillation/DPO switches (developer)",
    ),
    # Cards
    ("POST", "/api/v2/card", ".submit_card", "Submit a card"),
    ("POST", "/api/v2/card/batch", ".submit_batch", "Submit batch cards"),
    ("POST", "/api/v2/dispatch", ".sideload_dispatch", "Side-load dispatch"),
    ("POST", "/api/v2/card/rollback", ".card_rollback", "Rollback card"),
    ("GET", "/api/v2/cards", ".list_cards", "List cards"),
    ("GET", "/api/v2/card/{id}", ".get_card", "Get card by ID"),
    ("GET", "/api/v2/card/approval/{id}", ".card_approval_trail", "Card approval trail"),
    ("POST", "/api/v2/card-unified", ".card_unified_submit", "Submit unified card"),
    ("POST", "/api/v2/cards/plan", ".card_plan", "Get card execution plan"),
    ("POST", "/api/v2/cache", ".cache_stats", "Cache stats"),
    # Card gate
    ("GET", "/api/v2/card-gate/stats", ".card_gate_stats", "Card Gate stats"),
    ("GET", "/api/v2/card-gate/history", ".card_gate_history", "Card Gate approval history"),
    ("GET", "/api/v2/card-gate/config", ".card_gate_config", "Card Gate config"),
    ("POST", "/api/v2/card-gate/config", ".card_gate_config_set", "Set Card Gate config"),
    # Card types
    ("GET", "/api/v2/card-types", ".card_types_list", "List card types"),
    ("POST", "/api/v2/card-types", ".card_types_register", "Register card type"),
    # Approvals
    ("GET", "/api/v2/approvals", ".list_approvals", "List approvals"),
    ("POST", "/api/v2/approvals", ".approval_respond", "Respond to approval"),
    ("GET", "/api/v2/approvals/pending", ".gate_pending", "Card Gate pending"),
    ("POST", "/api/v2/approvals/respond", ".gate_respond", "Approve/reject held card"),
    # Pending queue
    ("GET", "/api/v2/pending", ".pending_list", "Pending queue list"),
    ("POST", "/api/v2/pending/approve", ".pending_approve", "Approve pending card"),
    ("POST", "/api/v2/pending/reject", ".pending_reject", "Reject pending card"),
    ("POST", "/api/v2/pending/escalate", ".pending_escalate", "Escalate to convention"),
    ("POST", "/api/v2/pending/priority", ".pending_priority", "Set pending priority"),
    ("GET", "/api/v2/pending/stats", ".pending_stats", "Pending queue stats"),
    # Cell
    ("POST", "/api/v2/cell/stop", ".cell_stop", "Emergency stop cell"),
    ("GET", "/api/v2/cell/liveness", ".cell_liveness", "Cell liveness check"),
    # Cluster (multi-cell orchestration)
    ("GET", "/api/v2/cluster/status", ".cluster_status", "Cluster state + composites"),
    ("GET", "/api/v2/cluster/composites", ".cluster_composites", "List L3B composites"),
    ("POST", "/api/v2/cluster/expand", ".cluster_expand", "Expand: register new Cell"),
    ("POST", "/api/v2/cluster/shrink", ".cluster_shrink", "Remove Cell + cleanup composites"),
    # Agent
    ("GET", "/api/v2/agents", ".agent_list", "List all agents"),
    ("GET", "/api/v2/agent/select/{id}", ".agent_select", "Select agent by id"),
    ("POST", "/api/v2/agent/select", ".agent_select_by", "Select agent by role/domain"),
    ("POST", "/api/v2/agent/preconnect", ".agent_preconnect", "Pre-connect verification"),
    ("POST", "/api/v2/agent/direct", ".agent_direct", "Start/continue direct session"),
    ("POST", "/api/v2/agent/direct/close", ".agent_direct_close", "Close direct session"),
    ("GET", "/api/v2/agent/reachable/{id}", ".agent_reachable", "Agent session reachable"),
    ("POST", "/api/v2/agent/review", ".agent_review_message", "External LLM review message"),
    # Settings
    ("GET", "/api/v2/settings", ".settings", "Get settings"),
    ("POST", "/api/v2/settings", ".set_settings", "Set settings"),
    # Security
    ("POST", "/api/v2/security/check", ".security_check", "Check action against all gates"),
    ("GET", "/api/v2/security/stats", ".security_stats", "Security check statistics"),
    ("POST", "/api/v2/trust/check", ".trust_check", "Evaluate content trust"),
    ("GET", "/api/v2/trust/stats", ".trust_stats", "Content trust statistics"),
    # Memory
    ("POST", "/api/v2/memory/store", ".memory_store", "Store in memory ring"),
    ("POST", "/api/v2/memory/recall", ".memory_recall", "Recall from memory rings"),
    ("GET", "/api/v2/memory/stats", ".memory_stats", "Memory statistics"),
    ("GET", "/api/v2/memory/graph", ".memory_graph_status", "R5 graph switch state + stats"),
    ("PUT", "/api/v2/memory/graph", ".memory_graph_set", "Toggle R5 graph switch (persisted)"),
    ("POST", "/api/v2/memory/graph/compact", ".memory_graph_compact", "Run graph reduction (dry_run by default)"),
    ("POST", "/api/v2/memory/graph/edge", ".memory_graph_edge", "Add a semantic edge (contradicts/depends_on/refines)"),
    ("GET", "/api/v2/memory/graph/semantic", ".memory_graph_semantic", "List semantic edges"),
    ("GET", "/api/v2/memory/mer", ".memory_mer_status", "Mer symbolization state + stats"),
    ("PUT", "/api/v2/memory/mer", ".memory_mer_set", "Toggle Mer side-channel (persisted)"),
    ("POST", "/api/v2/memory/mer/transform", ".memory_mer_transform", "Run one Mer pass (manual)"),
    # Shell
    ("POST", "/api/v2/shell", ".shell_dispatch", "Shell command dispatch"),
    ("GET", "/api/v2/shell/autocomplete", ".shell_autocomplete", "Shell auto-complete hints"),
    ("GET", "/api/v2/shell/commands", ".shell_commands", "Shell available commands"),
    # MCP
    ("POST", "/api/v2/mcp/import", ".mcp_import", "Import MCP server"),
    ("GET", "/api/v2/mcp/servers", ".mcp_list", "List MCP servers"),
    ("DELETE", "/api/v2/mcp/servers", ".mcp_remove", "Remove MCP server"),
    # MCP server mode (expose Praxis capabilities to external agents)
    ("GET", "/api/v2/mcp/tools/list", "l4.api_handlers.api_handlers_mcp.handle_mcp_tools_list", "MCP tools/list"),
    ("POST", "/api/v2/mcp/tools/call", "l4.api_handlers.api_handlers_mcp.handle_mcp_tools_call", "MCP tools/call"),
    ("GET", "/api/v2/mcp/ping", "l4.api_handlers.api_handlers_mcp.handle_mcp_ping", "MCP ping"),
    # Plugins
    ("GET", "/api/v2/plugins", ".plugin_list", "List installed plugins"),
    ("POST", "/api/v2/plugins/tool", ".plugin_install_tool", "Install tool plugin"),
    ("DELETE", "/api/v2/plugins", ".plugin_remove", "Remove plugin"),
    ("POST", "/api/v2/plugins/mcp", ".plugin_install_mcp", "Install MCP server as plugin"),
    ("GET", "/api/v2/plugins/stats", ".plugin_stats", "Plugin statistics"),
    # Shell commands
    (
        "GET",
        "/api/v2/commands",
        "l4.api_handlers.api_handlers_commands.handle_commands_list",
        "List all commands (system + user)",
    ),
    (
        "POST",
        "/api/v2/commands",
        "l4.api_handlers.api_handlers_commands.handle_commands_register",
        "Register a user command",
    ),
    (
        "DELETE",
        "/api/v2/commands/{name}",
        "l4.api_handlers.api_handlers_commands.handle_commands_remove",
        "Unregister a user command",
    ),
    (
        "PUT",
        "/api/v2/commands/{name}",
        "l4.api_handlers.api_handlers_commands.handle_commands_update",
        "Update a user command",
    ),
    # Tools & counters
    ("GET", "/api/v2/tools", ".tool_stats", "Tool stats"),
    ("POST", "/api/v2/tools/policy", ".tool_policy_set", "Set tool visibility policy"),
    ("GET", "/api/v2/tools/policy", ".tool_policy_list", "List tool visibility policies"),
    ("DELETE", "/api/v2/tools/policy", ".tool_policy_remove", "Remove tool visibility policy"),
    ("GET", "/api/v2/tools/locales", ".list_tools_v1", "List tools with locale"),
    ("GET", "/api/v2/locales", ".list_locales", "List available locales"),
    ("GET", "/api/v2/loops", ".loop_stats", "Loop stats"),
    ("GET", "/api/v2/loops/recent", ".loops_recent", "Recent loops"),
    # Tokens
    ("GET", "/api/v2/tokens", ".token_stats", "Token stats"),
    ("GET", "/api/v2/tokens/cells", ".token_cells", "Token per Cell"),
    ("GET", "/api/v2/tokens/global", ".token_global", "Token global summary"),
    # Constitution
    (
        "GET",
        "/api/v2/constitution",
        "l4.api_handlers.api_handlers_constitution.handle_constitution_get",
        "Get full constitution state",
    ),
    (
        "PUT",
        "/api/v2/constitution/rules",
        "l4.api_handlers.api_handlers_constitution.handle_constitution_rules_update",
        "Add/update custom rules",
    ),
    (
        "DELETE",
        "/api/v2/constitution/rules",
        "l4.api_handlers.api_handlers_constitution.handle_constitution_rules_clear",
        "Clear all custom rules",
    ),
    (
        "POST",
        "/api/v2/constitution/reload",
        "l4.api_handlers.api_handlers_constitution.handle_constitution_reload",
        "Reload constitution from file",
    ),
    (
        "GET",
        "/api/v2/constitution/summary",
        "l4.api_handlers.api_handlers_constitution.handle_constitution_summary",
        "LLM-readable constitution summary",
    ),
    # Discussion / Layer 3
    (
        "POST",
        "/api/v2/discussion/start",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_start",
        "Start discussion for an issue",
    ),
    (
        "GET",
        "/api/v2/discussion/sessions",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_sessions",
        "List all discussion sessions",
    ),
    (
        "GET",
        "/api/v2/discussion/reports",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_reports",
        "List all reports",
    ),
    (
        "GET",
        "/api/v2/discussion/{session_id}",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_get",
        "Get session status",
    ),
    (
        "GET",
        "/api/v2/discussion/{session_id}/answers",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_answers",
        "Get raw cell answers",
    ),
    (
        "GET",
        "/api/v2/discussion/{session_id}/report",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_report",
        "Get aggregated report",
    ),
    (
        "POST",
        "/api/v2/discussion/{session_id}/supplement",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_supplement",
        "Submit supplement issue",
    ),
    (
        "POST",
        "/api/v2/discussion/push-to-l3a",
        "l4.api_handlers.api_handlers_discussion.handle_discussion_push_l3a",
        "Push report to L3A",
    ),
    # L3A ASK clarification
    (
        "POST",
        "/api/v2/l3a/ask/status",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_ask_status",
        "Get pending clarification state of an L3A session",
    ),
    (
        "POST",
        "/api/v2/l3a/ask/answer",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_ask_answer",
        "Submit answers to pending clarification and resume",
    ),
    # L3A session contract (language-agnostic TUI/desktop client surface)
    (
        "POST",
        "/api/v2/l3a/sessions",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_session_create",
        "Create an L3A session",
    ),
    (
        "GET",
        "/api/v2/l3a/sessions",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_session_list",
        "List active L3A sessions",
    ),
    (
        "GET",
        "/api/v2/l3a/sessions/{session_id}",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_session_get",
        "L3A session detail (info + todos)",
    ),
    (
        "GET",
        "/api/v2/l3a/sessions/{session_id}/messages",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_session_messages",
        "Cursor-paged session message history",
    ),
    (
        "POST",
        "/api/v2/l3a/sessions/{session_id}/send",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_session_send",
        "Send intent / continue a session",
    ),
    (
        "POST",
        "/api/v2/l3a/sessions/{session_id}/close",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_session_close",
        "Close and archive a session",
    ),
    (
        "POST",
        "/api/v2/l3a/sessions/{session_id}/compress",
        "l4.api_handlers.api_handlers_l3a.handle_l3a_session_compress",
        "Compress session history",
    ),
    # Agent config
    (
        "GET",
        "/api/v2/agents/config",
        "l4.api_handlers.api_handlers_agent.handle_agent_config_get",
        "Get agent config (roles, clearance, priority, role_map)",
    ),
    (
        "PUT",
        "/api/v2/agents/config",
        "l4.api_handlers.api_handlers_agent.handle_agent_config_set",
        "Update agent config at runtime",
    ),
    # Provider management
    (
        "GET",
        "/api/v2/providers",
        "l4.api_handlers.api_handlers_providers.handle_providers_list",
        "List all LLM providers",
    ),
    (
        "POST",
        "/api/v2/providers",
        "l4.api_handlers.api_handlers_providers.handle_providers_register",
        "Register a new provider",
    ),
    (
        "DELETE",
        "/api/v2/providers/{name}",
        "l4.api_handlers.api_handlers_providers.handle_providers_remove",
        "Unregister a provider",
    ),
    (
        "GET",
        "/api/v2/providers/{name}/health",
        "l4.api_handlers.api_handlers_providers.handle_providers_health",
        "Test provider connectivity",
    ),
    (
        "PUT",
        "/api/v2/providers/{name}/config",
        "l4.api_handlers.api_handlers_providers.handle_providers_config",
        "Update provider configuration",
    ),
    # Model spec viewer / updater
    (
        "GET",
        "/api/v2/model-spec",
        "l4.api_handlers.api_handlers_providers.handle_model_spec_list",
        "List all model specs",
    ),
    (
        "PUT",
        "/api/v2/model-spec/{name}",
        "l4.api_handlers.api_handlers_providers.handle_model_spec_update",
        "Update a model spec",
    ),
    (
        "GET",
        "/api/v2/model-spec/{name}/strategy",
        "l4.api_handlers.api_handlers_providers.handle_model_strategy_get",
        "Current strategy of a model spec",
    ),
    (
        "PUT",
        "/api/v2/model-spec/{name}/strategy",
        "l4.api_handlers.api_handlers_providers.handle_model_strategy_apply",
        "Apply a named strategy pack to a model spec",
    ),
    (
        "DELETE",
        "/api/v2/model-spec/{name}/strategy",
        "l4.api_handlers.api_handlers_providers.handle_model_strategy_clear",
        "Clear strategy, restore executor defaults",
    ),
    (
        "PUT",
        "/api/v2/model-spec/strategy/apply",
        "l4.api_handlers.api_handlers_providers.handle_model_strategy_apply_many",
        "Apply a strategy to many executors",
    ),
    (
        "GET",
        "/api/v2/model-spec/overview",
        "l4.api_handlers.api_handlers_providers.handle_model_spec_overview",
        "Full model panel state (specs, caps, strategies, tiers)",
    ),
    (
        "GET",
        "/api/v2/model-spec/caps",
        "l4.api_handlers.api_handlers_providers.handle_think_caps_get",
        "Current reasoning caps",
    ),
    (
        "PUT",
        "/api/v2/model-spec/caps",
        "l4.api_handlers.api_handlers_providers.handle_think_caps_set",
        "Set reasoning caps",
    ),
    (
        "GET",
        "/api/v2/model-spec/peer",
        "l4.api_handlers.api_handlers_providers.handle_peer_strategy_get",
        "Peer think scopes state",
    ),
    (
        "PUT",
        "/api/v2/model-spec/peer",
        "l4.api_handlers.api_handlers_providers.handle_peer_strategy_apply",
        "Apply strategy pack to a think scope",
    ),
    (
        "DELETE",
        "/api/v2/model-spec/peer",
        "l4.api_handlers.api_handlers_providers.handle_peer_strategy_clear",
        "Clear strategy from a think scope",
    ),
    # SubAgent platform config
    (
        "GET",
        "/api/v2/subagent/defaults",
        "l4.api_handlers.api_handlers_providers.handle_subagent_defaults",
        "SubAgent platform defaults",
    ),
    (
        "PUT",
        "/api/v2/subagent/defaults",
        "l4.api_handlers.api_handlers_providers.handle_subagent_defaults_update",
        "Update subagent defaults",
    ),
    (
        "GET",
        "/api/v2/subagent/specs/{name}",
        "l4.api_handlers.api_handlers_providers.handle_subagent_spec_config",
        "Per-subagent model config",
    ),
    (
        "PUT",
        "/api/v2/subagent/specs/{name}",
        "l4.api_handlers.api_handlers_providers.handle_subagent_spec_config_update",
        "Update per-subagent config",
    ),
    # Scout config
    ("GET", "/api/v2/scout/config", "l4.api_handlers.api_handlers_providers.handle_scout_config", "Scout model config"),
    (
        "PUT",
        "/api/v2/scout/config",
        "l4.api_handlers.api_handlers_providers.handle_scout_config_update",
        "Update scout config",
    ),
    # R4Agent config
    ("GET", "/api/v2/r4/config", "l4.api_handlers.api_handlers_providers.handle_r4_config", "R4Agent model config"),
    (
        "PUT",
        "/api/v2/r4/config",
        "l4.api_handlers.api_handlers_providers.handle_r4_config_update",
        "Update R4Agent config",
    ),
    # Convention config
    (
        "GET",
        "/api/v2/convention/config",
        "l4.api_handlers.api_handlers_providers.handle_convention_config",
        "Convention model config",
    ),
    (
        "PUT",
        "/api/v2/convention/config",
        "l4.api_handlers.api_handlers_providers.handle_convention_config_update",
        "Update convention config",
    ),
    # StatsCenter (unified metrics)
    ("POST", "/api/v2/stats/query", "l4.api_handlers.api_handlers_stats.handle_stats_query", "Aggregated metric query"),
    ("GET", "/api/v2/stats/top", "l4.api_handlers.api_handlers_stats.handle_stats_top", "Cross-Cell metric ranking"),
    (
        "GET",
        "/api/v2/stats/live",
        "l4.api_handlers.api_handlers_stats.handle_stats_live",
        "Real-time metric stream (SSE)",
    ),
    # RecordCenter (unified error/log/reference)
    (
        "POST",
        "/api/v2/records/query",
        "l4.api_handlers.api_handlers_records.handle_records_query",
        "Unified query across error/log/reference",
    ),
    (
        "GET",
        "/api/v2/records/stats",
        "l4.api_handlers.api_handlers_records.handle_records_stats",
        "Aggregated record stats",
    ),
    (
        "POST",
        "/api/v2/records/export",
        "l4.api_handlers.api_handlers_records.handle_records_export",
        "Export records to JSON",
    ),
    (
        "POST",
        "/api/v2/records/bridge",
        "l4.api_handlers.api_handlers_records.handle_records_bridge",
        "Bridge record metrics to StatsCenter",
    ),
    # Communication
    ("GET", "/api/v2/communication/stats", ".comm_stats", "Communication stats"),
    ("GET", "/api/v2/communication/recent", ".comm_recent", "Recent communication"),
    # Cron
    ("GET", "/api/v2/cron", ".cron_list", "List cron schedules"),
    ("POST", "/api/v2/cron", ".cron_add", "Add cron schedule"),
    ("DELETE", "/api/v2/cron", ".cron_remove", "Remove cron schedule"),
    # Credentials
    ("GET", "/api/v2/credentials", ".credential_status", "Credential vault status"),
    ("POST", "/api/v2/credentials", ".credential_set", "Set credential"),
    ("DELETE", "/api/v2/credentials", ".credential_delete", "Delete credential"),
    # Auth (token lifecycle — frontend login state contract)
    (
        "POST",
        "/api/v2/auth/login",
        "l4.api_handlers.api_handlers_auth.handle_auth_login",
        "Issue an auth token for an identity",
    ),
    ("POST", "/api/v2/auth/logout", "l4.api_handlers.api_handlers_auth.handle_auth_logout", "Revoke an auth token"),
    (
        "POST",
        "/api/v2/auth/refresh",
        "l4.api_handlers.api_handlers_auth.handle_auth_refresh",
        "Exchange a valid token for a new one",
    ),
    # WebSocket bridge discovery
    ("GET", "/api/v2/ws", "l4.ws.ws_bridge.handle_ws_info", "WebSocket bridge connection info"),
    # FS (FilesystemPort contract — frontend file tree)
    ("GET", "/api/v2/fs/tree", "l4.api_handlers.api_handlers_fs.handle_fs_tree", "List a directory tree"),
    ("GET", "/api/v2/fs/read", "l4.api_handlers.api_handlers_fs.handle_fs_read", "Read a file"),
    ("POST", "/api/v2/fs/watch", "l4.api_handlers.api_handlers_fs.handle_fs_watch", "Watch a directory for changes"),
    ("POST", "/api/v2/fs/unwatch", "l4.api_handlers.api_handlers_fs.handle_fs_unwatch", "Stop watching a directory"),
    # User profile (side-channel — intent parsing / decision reference)
    (
        "GET",
        "/api/v2/profile",
        "l4.api_handlers.api_handlers_profile.handle_profile_list",
        "List users with live profiles",
    ),
    (
        "GET",
        "/api/v2/profile/{user_id}",
        "l4.api_handlers.api_handlers_profile.handle_profile_get",
        "Profile snapshot (kinds filter)",
    ),
    (
        "POST",
        "/api/v2/profile/{user_id}/ingest",
        "l4.api_handlers.api_handlers_profile.handle_profile_ingest",
        "Record a typed profile fact",
    ),
    (
        "POST",
        "/api/v2/profile/{user_id}/refine",
        "l4.api_handlers.api_handlers_profile.handle_profile_refine",
        "Synthesize trait entries",
    ),
    (
        "GET",
        "/api/v2/profile/{user_id}/export",
        "l4.api_handlers.api_handlers_profile.handle_profile_export",
        "Portable profile payload",
    ),
    (
        "POST",
        "/api/v2/profile/{user_id}/import",
        "l4.api_handlers.api_handlers_profile.handle_profile_import",
        "Restore a profile payload",
    ),
    (
        "DELETE",
        "/api/v2/profile/{user_id}",
        "l4.api_handlers.api_handlers_profile.handle_profile_clear",
        "Clear a user's profile",
    ),
    # Bootstrap
    ("GET", "/api/v2/bootstrap/status", ".bootstrap_status", "Check if bootstrap needed"),
    ("GET", "/api/v2/bootstrap/defaults", ".bootstrap_defaults", "Get default config"),
    ("POST", "/api/v2/bootstrap/apply", ".bootstrap_apply", "Apply config"),
    # System Lifecycle
    ("POST", "/api/v2/boot", ".boot", "Cold boot the system"),
    ("POST", "/api/v2/shutdown", ".shutdown", "Graceful shutdown"),
    ("POST", "/api/v2/reboot", ".reboot", "Warm restart (preserves memories)"),
    ("POST", "/api/v2/reload", ".reload", "Hot-reload constitution/config/tools"),
    ("POST", "/api/v2/reset", ".reset", "Factory reset (wipe all state + reboot)"),
    ("GET", "/api/v2/boot/status", ".boot_status", "Boot status and OS health"),
    # Export
    ("GET", "/api/v2/export", ".export_counter", "Export counter data"),
    ("GET", "/api/v2/metrics", ".export_metrics", "Export Prometheus metrics"),
    # Diff / Sandbox API
    (
        "POST",
        "/api/v2/diff/structured",
        "l4.api.api_handlers_diff.diff_structured",
        "Get structured diff for sandbox-staged file",
    ),
    ("POST", "/api/v2/diff/history", "l4.api.api_handlers_diff.diff_history", "List sandbox entries"),
    ("POST", "/api/v2/diff/colors", "l4.api.api_handlers_diff.diff_colors", "Get/set/reset diff color scheme"),
    # Rollback
    ("GET", "/api/v2/rollback/context", ".rollback_context", "Current rollback context"),
    # Session
    ("GET", "/api/v2/session/state", ".session_state", "Get current session state"),
    # ── Error Bus ──
    ("POST", "/api/v2/logs/errors", "l3.error_bus.api.handle_log_errors", "Query error logs"),
    ("POST", "/api/v2/logs/errors/detail", "l3.error_bus.api.handle_log_errors_detail", "Error detail by fingerprint"),
    ("GET", "/api/v2/logs/errors/stats", "l3.error_bus.api.handle_log_errors_stats", "Error statistics"),
    ("POST", "/api/v2/logs/errors/trend", "l3.error_bus.api.handle_log_errors_trend", "Error trend"),
    ("POST", "/api/v2/logs/errors/clear", "l3.error_bus.api.handle_log_errors_clear", "Clear error buffer"),
    ("POST", "/api/v2/logs/errors/export", "l3.error_bus.api.handle_log_errors_export", "Export errors"),
    # ── Log Service ──
    ("POST", "/api/v2/logs/query", "l3.bus.log.handle_log_query", "Query logs"),
    ("GET", "/api/v2/logs/recent", "l3.bus.log.handle_log_recent", "Recent log entries"),
    ("GET", "/api/v2/logs/stats", "l3.bus.log.handle_log_stats", "Log statistics"),
    ("POST", "/api/v2/logs/export", "l3.bus.log.handle_log_export", "Export logs"),
    # ── Config API ──
    ("POST", "/api/v2/config", "l4.api_handlers.api_handlers_config.handle_config_list", "List config"),
    ("POST", "/api/v2/config/get", "l4.api_handlers.api_handlers_config.handle_config_get", "Get config value"),
    ("PUT", "/api/v2/config/set", "l4.api_handlers.api_handlers_config.handle_config_set", "Set config"),
    (
        "GET",
        "/api/v2/config/categories",
        "l4.api_handlers.api_handlers_config.handle_config_categories",
        "List categories",
    ),
    # ── File Editor ──
    ("POST", "/api/v2/fs/edit", "l3.services.file_editor.handle_fs_edit", "Semantic file edit"),
    ("POST", "/api/v2/fs/batch-edit", "l3.services.file_editor.handle_fs_batch_edit", "Batch edit"),
    ("POST", "/api/v2/fs/history", "l3.services.file_editor.handle_fs_history", "File history"),
    ("POST", "/api/v2/fs/undo", "l3.services.file_editor.handle_fs_undo", "Undo"),
    ("POST", "/api/v2/fs/redo", "l3.services.file_editor.handle_fs_redo", "Redo"),
    ("POST", "/api/v2/fs/patch", "l3.services.file_editor.handle_fs_patch_create", "Create patch"),
    ("POST", "/api/v2/fs/patch/apply", "l3.services.file_editor.handle_fs_patch_apply", "Apply patch"),
    ("POST", "/api/v2/fs/patch/revert", "l3.services.file_editor.handle_fs_patch_revert", "Revert patch"),
    ("POST", "/api/v2/fs/patches", "l3.services.file_editor.handle_fs_patch_list", "List patches"),
    ("POST", "/api/v2/fs/patch/get", "l3.services.file_editor.handle_fs_patch_get", "Get patch detail"),
    # ── Prompt Engine ──
    ("POST", "/api/v2/prompt/build", "l3.services.prompt_engine.handle_prompt_build", "Build prompt"),
    ("POST", "/api/v2/prompt/context", "l3.services.prompt_engine.handle_prompt_context", "Context assembly"),
    ("GET", "/api/v2/prompt/templates", "l3.services.prompt_engine.handle_prompt_templates", "List templates"),
    (
        "POST",
        "/api/v2/prompt/template",
        "l3.services.prompt_engine.handle_prompt_template_register",
        "Register template",
    ),
    # ── LSP Manager ──
    ("POST", "/api/v2/lsp/diagnostics", "l4.lsp.lsp_manager.handle_lsp_diagnostics", "File diagnostics"),
    ("POST", "/api/v2/lsp/hover", "l4.lsp.lsp_manager.handle_lsp_hover", "Hover info"),
    ("GET", "/api/v2/lsp/servers", "l4.lsp.lsp_manager.handle_lsp_servers", "List LSP servers"),
    ("POST", "/api/v2/lsp/start", "l4.lsp.lsp_manager.handle_lsp_start", "Start LSP server"),
    ("POST", "/api/v2/lsp/stop", "l4.lsp.lsp_manager.handle_lsp_stop", "Stop LSP server"),
    ("POST", "/api/v2/lsp/feedback", "l4.lsp.lsp_manager.handle_lsp_feedback", "Post-edit feedback"),
    # ── SubAgent ──
    ("POST", "/api/v2/subagent/dispatch", "l3.agent.subagent_framework.handle_subagent_dispatch", "Dispatch subagent"),
    ("POST", "/api/v2/subagent/result", "l3.agent.subagent_framework.handle_subagent_result", "Get result"),
    ("POST", "/api/v2/subagent/cancel", "l3.agent.subagent_framework.handle_subagent_cancel", "Cancel task"),
    ("POST", "/api/v2/subagent/tasks", "l3.agent.subagent_framework.handle_subagent_list", "List tasks"),
    ("GET", "/api/v2/subagent/specs", "l3.agent.subagent_framework.handle_subagent_specs", "List specs"),
    ("POST", "/api/v2/subagent/spec", "l3.agent.subagent_framework.handle_subagent_spec_register", "Register spec"),
    ("POST", "/api/v2/subagent/merge", "l3.agent.subagent_framework.handle_subagent_merge", "Merge results"),
    # ── Search Engine ──
    ("POST", "/api/v2/search", "l4.search.search_engine.handle_search", "Unified search"),
    ("POST", "/api/v2/search/semantic", "l4.search.search_engine.handle_search_semantic", "Semantic search"),
    ("POST", "/api/v2/search/symbol", "l4.search.search_engine.handle_search_symbol", "Symbol search"),
    ("POST", "/api/v2/search/docs", "l4.search.search_engine.handle_search_docs", "Doc search"),
    ("POST", "/api/v2/search/docs/index", "l4.search.search_engine.handle_search_index_doc", "Index doc"),
    # ── Session Export ──
    ("POST", "/api/v2/session/export", "l3.services.session_export.handle_session_export", "Export session"),
    ("POST", "/api/v2/session/import", "l3.services.session_export.handle_session_import", "Import session"),
    ("GET", "/api/v2/session/snapshots", "l3.services.session_export.handle_session_snapshots", "List snapshots"),
    (
        "POST",
        "/api/v2/session/snapshot",
        "l3.services.session_export.handle_session_snapshot_create",
        "Create snapshot",
    ),
    (
        "POST",
        "/api/v2/session/snapshot/restore",
        "l3.services.session_export.handle_session_snapshot_restore",
        "Restore snapshot",
    ),
    (
        "POST",
        "/api/v2/session/snapshot/delete",
        "l3.services.session_export.handle_session_snapshot_delete",
        "Delete snapshot",
    ),
    # ── SSE Bridge ──
    ("GET", "/api/v2/events", "l4.sse.sse_bridge.handle_sse", "SSE event stream"),
    # ── Resource Buffer ──
    ("GET", "/api/v2/buffer/status", "l3.resource_buffer.api.handle_buffer_status", "Buffer status"),
    ("POST", "/api/v2/buffer/commit", "l3.resource_buffer.api.handle_buffer_commit", "Commit buffer to disk"),
    ("POST", "/api/v2/buffer/diff", "l3.resource_buffer.api.handle_buffer_diff", "Show pending diff"),
    ("POST", "/api/v2/buffer/discard", "l3.resource_buffer.api.handle_buffer_discard", "Discard pending changes"),
    # Loop control (standalone handlers from api_handlers_loop.py)
    ("GET", "/api/v2/loop/config", ".loop_config_get", "Get loop control config"),
    ("POST", "/api/v2/loop/config", ".loop_config_set", "Set loop control config"),
    ("GET", "/api/v2/loop/auto-test", ".loop_auto_test_get", "AutoTestGate state + pending feedback"),
    ("PUT", "/api/v2/loop/auto-test", ".loop_auto_test_set", "Switch AutoTestGate mode (off|async)"),
    # Monitor (standalone functions from api_handlers_monitor.py)
    (
        "GET",
        "/api/v2/monitor/events",
        "l4.api_handlers.api_handlers_monitor.handle_monitor_events",
        "Query monitor events",
    ),
    (
        "GET",
        "/api/v2/monitor/stats",
        "l4.api_handlers.api_handlers_monitor.handle_monitor_stats",
        "Monitor event statistics",
    ),
    (
        "GET",
        "/api/v2/monitor/stream",
        "l4.api_handlers.api_handlers_monitor.handle_monitor_stream",
        "SSE monitor event stream",
    ),
    (
        "GET",
        "/api/v2/monitor/gate",
        "l4.api_handlers.api_handlers_monitor.handle_message_gate_list",
        "List message gate rules",
    ),
    (
        "POST",
        "/api/v2/monitor/gate",
        "l4.api_handlers.api_handlers_monitor.handle_message_gate_set",
        "Set message gate rule",
    ),
    (
        "DELETE",
        "/api/v2/monitor/gate/{id}",
        "l4.api_handlers.api_handlers_monitor.handle_message_gate_remove",
        "Remove message gate rule",
    ),
    # Skills (read public; mutation developer-only via SkillManager gate)
    ("GET", "/api/v2/skills", "l4.api_handlers.api_handlers_skills.handle_skills_list", "List skills"),
    ("GET", "/api/v2/skills/{name}", "l4.api_handlers.api_handlers_skills.handle_skills_get", "Get skill detail"),
    ("POST", "/api/v2/skills", "l4.api_handlers.api_handlers_skills.handle_skills_create", "Create skill (developer)"),
    (
        "PUT",
        "/api/v2/skills/{name}",
        "l4.api_handlers.api_handlers_skills.handle_skills_update",
        "Update skill (developer)",
    ),
    (
        "DELETE",
        "/api/v2/skills/{name}",
        "l4.api_handlers.api_handlers_skills.handle_skills_delete",
        "Delete skill (developer)",
    ),
    (
        "POST",
        "/api/v2/skills/reload",
        "l4.api_handlers.api_handlers_skills.handle_skills_reload",
        "Reload built-in skills (developer)",
    ),
    (
        "GET",
        "/api/v2/skills/permissions",
        "l4.api_handlers.api_handlers_skills.handle_skills_permissions",
        "Skill write-gate policy",
    ),
    (
        "GET",
        "/api/v2/skills/offensive-policy",
        "l4.api_handlers.api_handlers_skills.handle_skills_offensive_policy_get",
        "Skill offensive-posture gate policy",
    ),
    (
        "POST",
        "/api/v2/skills/offensive-policy",
        "l4.api_handlers.api_handlers_skills.handle_skills_offensive_policy_set",
        "Update skill offensive-posture gate (developer)",
    ),
    # CI review (card-triggered; read-only queries + runtime switch)
    ("GET", "/api/v2/ci/reviews", "l4.api_handlers.api_handlers_ci.handle_ci_reviews", "Query CI review reports"),
    (
        "GET",
        "/api/v2/ci/reviews/{card_id}",
        "l4.api_handlers.api_handlers_ci.handle_ci_review_get",
        "Single card CI review report",
    ),
    (
        "POST",
        "/api/v2/ci/reviews/{card_id}/rerun",
        "l4.api_handlers.api_handlers_ci.handle_ci_review_rerun",
        "Re-run CI review for a card",
    ),
    (
        "GET",
        "/api/v2/ci/config",
        "l4.api_handlers.api_handlers_ci.handle_ci_config_get",
        "CI review switch state + permissions",
    ),
    (
        "PUT",
        "/api/v2/ci/config",
        "l4.api_handlers.api_handlers_ci.handle_ci_config_set",
        "Toggle CI review runtime switch",
    ),
]
