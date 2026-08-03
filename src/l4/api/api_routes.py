"""API route registry — single source of truth for all routes.

Each route: (method, path, handler_ref, description)
  handler_ref: "module.function" for standalone functions
               ".method_name" for ApiHandlers mixin methods (resolved via getattr)
"""

# ── ApiHandlers mixin methods (prefixed with .) ──
# Resolved at runtime via getattr(api_gateway_instance, method_name)

API_ROUTES: list[tuple[str, str, str, str]] = [
    # Core system
    ("GET", "/api/health",             ".health",             "Kernel health"),
    ("GET", "/api/processes",          ".processes",          "List processes"),
    ("GET", "/api/devices",            ".devices",            "List devices"),
    ("GET", "/api/peers",              ".peers",              "List peers"),
    ("GET", "/api/syscalls",           ".syscalls",           "List syscalls"),
    ("GET", "/api/endpoints",          ".list_endpoints",     "List endpoints"),
    ("GET", "/api/mode",               ".tool_mode_get",      "Get tool mode"),
    ("PUT", "/api/mode",               ".tool_mode_set",      "Set tool mode"),

    # Cards
    ("POST", "/api/card",              ".submit_card",        "Submit a card"),
    ("POST", "/api/card/batch",        ".submit_batch",       "Submit batch cards"),
    ("POST", "/api/dispatch",          ".sideload_dispatch",  "Side-load dispatch"),
    ("POST", "/api/card/rollback",     ".card_rollback",      "Rollback card"),
    ("GET", "/api/cards",              ".list_cards",         "List cards"),
    ("GET", "/api/card/",              ".get_card",           "Get card by ID"),
    ("GET", "/api/card/approval/",     ".card_approval_trail","Card approval trail"),
    ("POST", "/api/card_unified",      ".card_unified_submit","Submit unified card"),
    ("POST", "/api/cards/plan",        ".card_plan",          "Get card execution plan"),
    ("POST", "/api/cache",             ".cache_stats",        "Cache stats"),

    # Card gate
    ("GET", "/api/card_gate/stats",    ".card_gate_stats",    "Card Gate stats"),
    ("GET", "/api/card_gate/history",  ".card_gate_history",  "Card Gate approval history"),
    ("GET", "/api/card_gate/config",   ".card_gate_config",   "Card Gate config"),
    ("POST", "/api/card_gate/config",  ".card_gate_config_set","Set Card Gate config"),

    # Card types
    ("GET", "/api/card_types",         ".card_types_list",    "List card types"),
    ("POST", "/api/card_types",        ".card_types_register","Register card type"),

    # Approvals
    ("GET", "/api/approvals",          ".list_approvals",     "List approvals"),
    ("POST", "/api/approvals",         ".approval_respond",   "Respond to approval"),
    ("GET", "/api/approvals/pending",  ".gate_pending",       "Card Gate pending"),
    ("POST", "/api/approvals/respond", ".gate_respond",       "Approve/reject held card"),

    # Pending queue
    ("GET", "/api/pending",            ".pending_list",       "Pending queue list"),
    ("POST", "/api/pending/approve",   ".pending_approve",    "Approve pending card"),
    ("POST", "/api/pending/reject",    ".pending_reject",     "Reject pending card"),
    ("POST", "/api/pending/escalate",  ".pending_escalate",   "Escalate to convention"),
    ("POST", "/api/pending/priority",  ".pending_priority",   "Set pending priority"),
    ("GET", "/api/pending/stats",      ".pending_stats",      "Pending queue stats"),

    # Cell
    ("POST", "/api/cell/stop",         ".cell_stop",          "Emergency stop cell"),
    ("GET", "/api/cell/liveness",      ".cell_liveness",      "Cell liveness check"),

    # Cluster (multi-cell orchestration)
    ("GET",  "/api/cluster/status",    ".cluster_status",     "Cluster state + composites"),
    ("GET",  "/api/cluster/composites",".cluster_composites", "List L3B composites"),
    ("POST", "/api/cluster/expand",    ".cluster_expand",     "Expand: register new Cell"),
    ("POST", "/api/cluster/shrink",    ".cluster_shrink",     "Remove Cell + cleanup composites"),

    # Agent
    ("GET", "/api/agents",             ".agent_list",         "List all agents"),
    ("GET", "/api/agent/select/",      ".agent_select",       "Select agent by id"),
    ("POST", "/api/agent/select",      ".agent_select_by",    "Select agent by role/domain"),
    ("POST", "/api/agent/preconnect",  ".agent_preconnect",   "Pre-connect verification"),
    ("POST", "/api/agent/direct",      ".agent_direct",       "Start/continue direct session"),
    ("POST", "/api/agent/direct/close",".agent_direct_close", "Close direct session"),
    ("GET", "/api/agent/reachable/",   ".agent_reachable",    "Agent session reachable"),
    ("POST", "/api/agent/review",      ".agent_review_message","External LLM review message"),

    # Settings
    ("GET", "/api/settings",           ".settings",           "Get settings"),
    ("POST", "/api/settings",          ".set_settings",       "Set settings"),

    # Security
    ("POST", "/api/security/check",    ".security_check",     "Check action against all gates"),
    ("GET", "/api/security/stats",     ".security_stats",     "Security check statistics"),
    ("POST", "/api/trust/check",       ".trust_check",        "Evaluate content trust"),
    ("GET", "/api/trust/stats",        ".trust_stats",        "Content trust statistics"),

    # Memory
    ("POST", "/api/memory/store",      ".memory_store",       "Store in memory ring"),
    ("POST", "/api/memory/recall",     ".memory_recall",      "Recall from memory rings"),
    ("GET", "/api/memory/stats",       ".memory_stats",       "Memory statistics"),
    ("GET", "/api/memory/graph",       ".memory_graph_status", "R5 graph switch state + stats"),
    ("PUT", "/api/memory/graph",       ".memory_graph_set",   "Toggle R5 graph switch (persisted)"),
    ("POST", "/api/memory/graph/compact", ".memory_graph_compact", "Run graph reduction (dry_run by default)"),
    ("POST", "/api/memory/graph/edge",    ".memory_graph_edge",   "Add a semantic edge (contradicts/depends_on/refines)"),
    ("GET", "/api/memory/graph/semantic", ".memory_graph_semantic", "List semantic edges"),

    # Shell
    ("POST", "/api/shell",             ".shell_dispatch",     "Shell command dispatch"),
    ("GET", "/api/shell/autocomplete", ".shell_autocomplete", "Shell auto-complete hints"),
    ("GET", "/api/shell/commands",     ".shell_commands",     "Shell available commands"),

    # MCP
    ("POST", "/api/mcp/import",        ".mcp_import",         "Import MCP server"),
    ("GET", "/api/mcp/servers",        ".mcp_list",           "List MCP servers"),
    ("DELETE", "/api/mcp/servers",     ".mcp_remove",         "Remove MCP server"),

    # MCP server mode (expose Praxis capabilities to external agents)
    ("GET", "/api/mcp/tools/list",
     "l4.api_handlers.api_handlers_mcp.handle_mcp_tools_list", "MCP tools/list"),
    ("POST", "/api/mcp/tools/call",
     "l4.api_handlers.api_handlers_mcp.handle_mcp_tools_call", "MCP tools/call"),
    ("GET", "/api/mcp/ping",
     "l4.api_handlers.api_handlers_mcp.handle_mcp_ping", "MCP ping"),

    # Plugins
    ("GET", "/api/plugins",            ".plugin_list",        "List installed plugins"),
    ("POST", "/api/plugins/tool",      ".plugin_install_tool","Install tool plugin"),
    ("DELETE", "/api/plugins",         ".plugin_remove",      "Remove plugin"),
    ("POST", "/api/plugins/mcp",       ".plugin_install_mcp", "Install MCP server as plugin"),
    ("GET", "/api/plugins/stats",      ".plugin_stats",       "Plugin statistics"),

    # Shell commands
    ("GET", "/api/v1/commands",        "l4.api_handlers.api_handlers_commands.handle_commands_list",  "List all commands (system + user)"),
    ("POST", "/api/v1/commands",       "l4.api_handlers.api_handlers_commands.handle_commands_register", "Register a user command"),
    ("DELETE", "/api/v1/commands/{name}","l4.api_handlers.api_handlers_commands.handle_commands_remove", "Unregister a user command"),
    ("PUT", "/api/v1/commands/{name}",  "l4.api_handlers.api_handlers_commands.handle_commands_update",  "Update a user command"),

    # Tools & counters
    ("GET", "/api/tools",              ".tool_stats",         "Tool stats"),
    ("POST", "/api/tools/policy",      ".tool_policy_set",    "Set tool visibility policy"),
    ("GET", "/api/tools/policy",       ".tool_policy_list",   "List tool visibility policies"),
    ("DELETE", "/api/tools/policy",    ".tool_policy_remove", "Remove tool visibility policy"),
    ("GET", "/api/v1/tools",           ".list_tools_v1",      "List tools with locale"),
    ("GET", "/api/v1/locales",         ".list_locales",       "List available locales"),
    ("GET", "/api/loops",              ".loop_stats",         "Loop stats"),
    ("GET", "/api/loops/recent",       ".loops_recent",       "Recent loops"),

    # Tokens
    ("GET", "/api/tokens",             ".token_stats",        "Token stats"),
    ("GET", "/api/tokens/cells",       ".token_cells",        "Token per Cell"),
    ("GET", "/api/tokens/global",      ".token_global",       "Token global summary"),

    # Constitution
    ("GET",  "/api/v2/constitution",              "l4.api_handlers.api_handlers_constitution.handle_constitution_get",           "Get full constitution state"),
    ("PUT",  "/api/v2/constitution/rules",         "l4.api_handlers.api_handlers_constitution.handle_constitution_rules_update",    "Add/update custom rules"),
    ("DELETE","/api/v2/constitution/rules",         "l4.api_handlers.api_handlers_constitution.handle_constitution_rules_clear",    "Clear all custom rules"),
    ("POST", "/api/v2/constitution/reload",        "l4.api_handlers.api_handlers_constitution.handle_constitution_reload",          "Reload constitution from file"),
    ("GET",  "/api/v2/constitution/summary",       "l4.api_handlers.api_handlers_constitution.handle_constitution_summary",         "LLM-readable constitution summary"),

    # Discussion / Layer 3
    ("POST", "/api/v2/discussion/start",                "l4.api_handlers.api_handlers_discussion.handle_discussion_start",                "Start discussion for an issue"),
    ("GET",  "/api/v2/discussion/sessions",              "l4.api_handlers.api_handlers_discussion.handle_discussion_sessions",              "List all discussion sessions"),
    ("GET",  "/api/v2/discussion/reports",               "l4.api_handlers.api_handlers_discussion.handle_discussion_reports",               "List all reports"),
    ("GET",  "/api/v2/discussion/{id}",                  "l4.api_handlers.api_handlers_discussion.handle_discussion_get",                  "Get session status"),
    ("GET",  "/api/v2/discussion/{id}/answers",          "l4.api_handlers.api_handlers_discussion.handle_discussion_answers",              "Get raw cell answers"),
    ("GET",  "/api/v2/discussion/{id}/report",           "l4.api_handlers.api_handlers_discussion.handle_discussion_report",               "Get aggregated report"),
    ("POST", "/api/v2/discussion/{id}/supplement",       "l4.api_handlers.api_handlers_discussion.handle_discussion_supplement",            "Submit supplement issue"),
    ("POST", "/api/v2/discussion/push-to-l3a",           "l4.api_handlers.api_handlers_discussion.handle_discussion_push_l3a",              "Push report to L3A"),

    # Agent config
    ("GET", "/api/v1/agents/config",   "l4.api_handlers.api_handlers_agent.handle_agent_config_get",  "Get agent config (roles, clearance, priority, role_map)"),
    ("PUT", "/api/v1/agents/config",   "l4.api_handlers.api_handlers_agent.handle_agent_config_set",  "Update agent config at runtime"),

    # Provider management
    ("GET",  "/api/v2/providers",              "l4.api_handlers.api_handlers_providers.handle_providers_list",           "List all LLM providers"),
    ("POST", "/api/v2/providers",              "l4.api_handlers.api_handlers_providers.handle_providers_register",        "Register a new provider"),
    ("DELETE","/api/v2/providers/{name}",       "l4.api_handlers.api_handlers_providers.handle_providers_remove",          "Unregister a provider"),
    ("GET",  "/api/v2/providers/{name}/health", "l4.api_handlers.api_handlers_providers.handle_providers_health",          "Test provider connectivity"),
    ("PUT",  "/api/v2/providers/{name}/config", "l4.api_handlers.api_handlers_providers.handle_providers_config",          "Update provider configuration"),

    # Model spec viewer / updater
    ("GET",  "/api/v2/model-spec",              "l4.api_handlers.api_handlers_providers.handle_model_spec_list",           "List all model specs"),
    ("PUT",  "/api/v2/model-spec/{name}",       "l4.api_handlers.api_handlers_providers.handle_model_spec_update",          "Update a model spec"),

    # SubAgent platform config
    ("GET",  "/api/v2/subagent/defaults",       "l4.api_handlers.api_handlers_providers.handle_subagent_defaults",          "SubAgent platform defaults"),
    ("PUT",  "/api/v2/subagent/defaults",       "l4.api_handlers.api_handlers_providers.handle_subagent_defaults_update",   "Update subagent defaults"),
    ("GET",  "/api/v2/subagent/specs/{name}",   "l4.api_handlers.api_handlers_providers.handle_subagent_spec_config",       "Per-subagent model config"),
    ("PUT",  "/api/v2/subagent/specs/{name}",   "l4.api_handlers.api_handlers_providers.handle_subagent_spec_config_update","Update per-subagent config"),

    # Scout config
    ("GET",  "/api/v2/scout/config",            "l4.api_handlers.api_handlers_providers.handle_scout_config",               "Scout model config"),
    ("PUT",  "/api/v2/scout/config",            "l4.api_handlers.api_handlers_providers.handle_scout_config_update",         "Update scout config"),

    # R4Agent config
    ("GET",  "/api/v2/r4/config",               "l4.api_handlers.api_handlers_providers.handle_r4_config",                  "R4Agent model config"),
    ("PUT",  "/api/v2/r4/config",               "l4.api_handlers.api_handlers_providers.handle_r4_config_update",            "Update R4Agent config"),

    # Convention config
    ("GET",  "/api/v2/convention/config",        "l4.api_handlers.api_handlers_providers.handle_convention_config",           "Convention model config"),
    ("PUT",  "/api/v2/convention/config",        "l4.api_handlers.api_handlers_providers.handle_convention_config_update",     "Update convention config"),

    # StatsCenter (unified metrics)
    ("POST", "/api/v2/stats/query",    "l4.api_handlers.api_handlers_stats.handle_stats_query",  "Aggregated metric query"),
    ("GET", "/api/v2/stats/top",       "l4.api_handlers.api_handlers_stats.handle_stats_top",    "Cross-Cell metric ranking"),
    ("GET", "/api/v2/stats/live",      "l4.api_handlers.api_handlers_stats.handle_stats_live",   "Real-time metric stream (SSE)"),

    # RecordCenter (unified error/log/reference)
    ("POST", "/api/v2/records/query",  "l4.api_handlers.api_handlers_records.handle_records_query",  "Unified query across error/log/reference"),
    ("GET",  "/api/v2/records/stats",  "l4.api_handlers.api_handlers_records.handle_records_stats",  "Aggregated record stats"),
    ("POST", "/api/v2/records/export", "l4.api_handlers.api_handlers_records.handle_records_export", "Export records to JSON"),
    ("POST", "/api/v2/records/bridge", "l4.api_handlers.api_handlers_records.handle_records_bridge", "Bridge record metrics to StatsCenter"),

    # Communication
    ("GET", "/api/communication/stats", ".comm_stats",        "Communication stats"),
    ("GET", "/api/communication/recent",".comm_recent",       "Recent communication"),

    # Cron
    ("GET", "/api/cron",               ".cron_list",          "List cron schedules"),
    ("POST", "/api/cron",              ".cron_add",           "Add cron schedule"),
    ("DELETE", "/api/cron",            ".cron_remove",        "Remove cron schedule"),

    # Credentials
    ("GET", "/api/credentials",        ".credential_status",  "Credential vault status"),
    ("POST", "/api/credentials",       ".credential_set",     "Set credential"),
    ("DELETE", "/api/credentials",     ".credential_delete",  "Delete credential"),

    # Bootstrap
    ("GET", "/api/bootstrap/status",   ".bootstrap_status",   "Check if bootstrap needed"),
    ("GET", "/api/bootstrap/defaults", ".bootstrap_defaults", "Get default config"),
    ("POST", "/api/bootstrap/apply",   ".bootstrap_apply",    "Apply config"),

    # System Lifecycle
    ("POST", "/api/boot",             ".boot",             "Cold boot the system"),
    ("POST", "/api/shutdown",         ".shutdown",         "Graceful shutdown"),
    ("POST", "/api/reboot",           ".reboot",           "Warm restart (preserves memories)"),
    ("POST", "/api/reload",           ".reload",           "Hot-reload constitution/config/tools"),
    ("POST", "/api/reset",            ".reset",            "Factory reset (wipe all state + reboot)"),
    ("GET",  "/api/boot/status",      ".boot_status",      "Boot status and OS health"),

    # Export
    ("GET", "/api/export",             ".export_counter",     "Export counter data"),
    ("GET", "/api/metrics",            ".export_metrics",     "Export Prometheus metrics"),

    # Diff / Sandbox API
    ("POST", "/api/diff/structured",   "l4.api.api_handlers_diff.diff_structured",   "Get structured diff for sandbox-staged file"),
    ("POST", "/api/diff/history",      "l4.api.api_handlers_diff.diff_history",      "List sandbox entries"),
    ("POST", "/api/diff/colors",       "l4.api.api_handlers_diff.diff_colors",       "Get/set/reset diff color scheme"),

    # Rollback
    ("GET", "/api/rollback/context",   ".rollback_context",   "Current rollback context"),

    # Session
    ("GET", "/api/session/state",      ".session_state",      "Get current session state"),

    # ── Error Bus ──
    ("POST", "/api/logs/errors",        "l3.error_bus.api.handle_log_errors",         "Query error logs"),
    ("POST", "/api/logs/errors/detail", "l3.error_bus.api.handle_log_errors_detail",  "Error detail by fingerprint"),
    ("GET",  "/api/logs/errors/stats",  "l3.error_bus.api.handle_log_errors_stats",   "Error statistics"),
    ("POST", "/api/logs/errors/trend",  "l3.error_bus.api.handle_log_errors_trend",   "Error trend"),
    ("POST", "/api/logs/errors/clear",  "l3.error_bus.api.handle_log_errors_clear",   "Clear error buffer"),
    ("POST", "/api/logs/errors/export", "l3.error_bus.api.handle_log_errors_export",  "Export errors"),

    # ── Log Service ──
    ("POST", "/api/logs/query",         "l3.bus.log.handle_log_query",                "Query logs"),
    ("GET",  "/api/logs/recent",        "l3.bus.log.handle_log_recent",               "Recent log entries"),
    ("GET",  "/api/logs/stats",         "l3.bus.log.handle_log_stats",                "Log statistics"),
    ("POST", "/api/logs/export",        "l3.bus.log.handle_log_export",               "Export logs"),

    # ── Config API ──
    ("POST", "/api/config",             "l4.api_handlers.api_handlers_config.handle_config_list","List config"),
    ("POST", "/api/config/get",         "l4.api_handlers.api_handlers_config.handle_config_get", "Get config value"),
    ("PUT",  "/api/config/set",         "l4.api_handlers.api_handlers_config.handle_config_set", "Set config"),
    ("GET",  "/api/config/categories",  "l4.api_handlers.api_handlers_config.handle_config_categories","List categories"),

    # ── File Editor ──
    ("POST", "/api/fs/edit",            "l3.services.file_editor.handle_fs_edit",           "Semantic file edit"),
    ("POST", "/api/fs/batch_edit",      "l3.services.file_editor.handle_fs_batch_edit",     "Batch edit"),
    ("POST", "/api/fs/history",         "l3.services.file_editor.handle_fs_history",        "File history"),
    ("POST", "/api/fs/undo",            "l3.services.file_editor.handle_fs_undo",           "Undo"),
    ("POST", "/api/fs/redo",            "l3.services.file_editor.handle_fs_redo",           "Redo"),
    ("POST", "/api/fs/patch",           "l3.services.file_editor.handle_fs_patch_create",   "Create patch"),
    ("POST", "/api/fs/patch/apply",     "l3.services.file_editor.handle_fs_patch_apply",    "Apply patch"),
    ("POST", "/api/fs/patch/revert",    "l3.services.file_editor.handle_fs_patch_revert",   "Revert patch"),
    ("POST", "/api/fs/patches",         "l3.services.file_editor.handle_fs_patch_list",     "List patches"),
    ("POST", "/api/fs/patch/get",       "l3.services.file_editor.handle_fs_patch_get",      "Get patch detail"),

    # ── Prompt Engine ──
    ("POST", "/api/prompt/build",       "l3.services.prompt_engine.handle_prompt_build",    "Build prompt"),
    ("POST", "/api/prompt/context",     "l3.services.prompt_engine.handle_prompt_context",  "Context assembly"),
    ("GET",  "/api/prompt/templates",   "l3.services.prompt_engine.handle_prompt_templates","List templates"),
    ("POST", "/api/prompt/template",    "l3.services.prompt_engine.handle_prompt_template_register","Register template"),

    # ── LSP Manager ──
    ("POST", "/api/lsp/diagnostics",    "l4.lsp.lsp_manager.handle_lsp_diagnostics",   "File diagnostics"),
    ("POST", "/api/lsp/hover",          "l4.lsp.lsp_manager.handle_lsp_hover",         "Hover info"),
    ("GET",  "/api/lsp/servers",        "l4.lsp.lsp_manager.handle_lsp_servers",       "List LSP servers"),
    ("POST", "/api/lsp/start",          "l4.lsp.lsp_manager.handle_lsp_start",         "Start LSP server"),
    ("POST", "/api/lsp/stop",           "l4.lsp.lsp_manager.handle_lsp_stop",          "Stop LSP server"),
    ("POST", "/api/lsp/feedback",       "l4.lsp.lsp_manager.handle_lsp_feedback",      "Post-edit feedback"),

    # ── SubAgent ──
    ("POST", "/api/subagent/dispatch",   "l3.agent.subagent_framework.handle_subagent_dispatch","Dispatch subagent"),
    ("POST", "/api/subagent/result",     "l3.agent.subagent_framework.handle_subagent_result",   "Get result"),
    ("POST", "/api/subagent/cancel",     "l3.agent.subagent_framework.handle_subagent_cancel",   "Cancel task"),
    ("POST", "/api/subagent/tasks",      "l3.agent.subagent_framework.handle_subagent_list",     "List tasks"),
    ("GET",  "/api/subagent/specs",      "l3.agent.subagent_framework.handle_subagent_specs",    "List specs"),
    ("POST", "/api/subagent/spec",       "l3.agent.subagent_framework.handle_subagent_spec_register","Register spec"),
    ("POST", "/api/subagent/merge",      "l3.agent.subagent_framework.handle_subagent_merge",    "Merge results"),

    # ── Search Engine ──
    ("POST", "/api/search",              "l4.search.search_engine.handle_search",                 "Unified search"),
    ("POST", "/api/search/semantic",     "l4.search.search_engine.handle_search_semantic",         "Semantic search"),
    ("POST", "/api/search/symbol",       "l4.search.search_engine.handle_search_symbol",            "Symbol search"),
    ("POST", "/api/search/docs",         "l4.search.search_engine.handle_search_docs",             "Doc search"),
    ("POST", "/api/search/docs/index",   "l4.search.search_engine.handle_search_index_doc",         "Index doc"),

    # ── Session Export ──
    ("POST", "/api/session/export",             "l3.services.session_export.handle_session_export",              "Export session"),
    ("POST", "/api/session/import",             "l3.services.session_export.handle_session_import",              "Import session"),
    ("GET",  "/api/session/snapshots",          "l3.services.session_export.handle_session_snapshots",            "List snapshots"),
    ("POST", "/api/session/snapshot",           "l3.services.session_export.handle_session_snapshot_create",      "Create snapshot"),
    ("POST", "/api/session/snapshot/restore",   "l3.services.session_export.handle_session_snapshot_restore",    "Restore snapshot"),
    ("POST", "/api/session/snapshot/delete",    "l3.services.session_export.handle_session_snapshot_delete",     "Delete snapshot"),

    # ── SSE Bridge ──
    ("GET",  "/api/events",             "l4.sse.sse_bridge.handle_sse",                  "SSE event stream"),

    # ── Resource Buffer ──
    ("GET",  "/api/buffer/status",  "l3.resource_buffer.api.handle_buffer_status",  "Buffer status"),
    ("POST", "/api/buffer/commit",  "l3.resource_buffer.api.handle_buffer_commit",  "Commit buffer to disk"),
    ("POST", "/api/buffer/diff",    "l3.resource_buffer.api.handle_buffer_diff",    "Show pending diff"),
    ("POST", "/api/buffer/discard", "l3.resource_buffer.api.handle_buffer_discard", "Discard pending changes"),

    # Loop control (standalone handlers from api_handlers_loop.py)
    ("GET",  "/api/loop/config",   ".loop_config_get", "Get loop control config"),
    ("POST", "/api/loop/config",   ".loop_config_set", "Set loop control config"),

    # Monitor (standalone functions from api_handlers_monitor.py)
    ("GET",  "/api/monitor/events",    "l4.api_handlers.api_handlers_monitor.handle_monitor_events",     "Query monitor events"),
    ("GET",  "/api/monitor/stats",     "l4.api_handlers.api_handlers_monitor.handle_monitor_stats",      "Monitor event statistics"),
    ("GET",  "/api/monitor/stream",    "l4.api_handlers.api_handlers_monitor.handle_monitor_stream",     "SSE monitor event stream"),
    ("GET",  "/api/monitor/gate",      "l4.api_handlers.api_handlers_monitor.handle_message_gate_list",  "List message gate rules"),
    ("POST", "/api/monitor/gate",      "l4.api_handlers.api_handlers_monitor.handle_message_gate_set",   "Set message gate rule"),
    ("DELETE","/api/monitor/gate/",    "l4.api_handlers.api_handlers_monitor.handle_message_gate_remove", "Remove message gate rule"),
]
