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

    # Shell
    ("POST", "/api/shell",             ".shell_dispatch",     "Shell command dispatch"),
    ("GET", "/api/shell/autocomplete", ".shell_autocomplete", "Shell auto-complete hints"),
    ("GET", "/api/shell/commands",     ".shell_commands",     "Shell available commands"),

    # MCP
    ("POST", "/api/mcp/import",        ".mcp_import",         "Import MCP server"),
    ("GET", "/api/mcp/servers",        ".mcp_list",           "List MCP servers"),
    ("DELETE", "/api/mcp/servers",     ".mcp_remove",         "Remove MCP server"),

    # Plugins
    ("GET", "/api/plugins",            ".plugin_list",        "List installed plugins"),
    ("POST", "/api/plugins/tool",      ".plugin_install_tool","Install tool plugin"),
    ("DELETE", "/api/plugins",         ".plugin_remove",      "Remove plugin"),
    ("POST", "/api/plugins/mcp",       ".plugin_install_mcp", "Install MCP server as plugin"),
    ("GET", "/api/plugins/stats",      ".plugin_stats",       "Plugin statistics"),

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

    # Export
    ("GET", "/api/export",             ".export_counter",     "Export counter data"),
    ("GET", "/api/metrics",            ".export_metrics",     "Export Prometheus metrics"),

    # Rollback
    ("GET", "/api/rollback/context",   ".rollback_context",   "Current rollback context"),

    # Session
    ("GET", "/api/session/state",      ".session_state",      "Get current session state"),

    # ── Error Bus ──
    ("POST", "/api/logs/errors",        "services.error_bus.handle_log_errors",         "Query error logs"),
    ("POST", "/api/logs/errors/detail", "services.error_bus.handle_log_errors_detail",  "Error detail by fingerprint"),
    ("GET",  "/api/logs/errors/stats",  "services.error_bus.handle_log_errors_stats",   "Error statistics"),
    ("POST", "/api/logs/errors/trend",  "services.error_bus.handle_log_errors_trend",   "Error trend"),
    ("POST", "/api/logs/errors/clear",  "services.error_bus.handle_log_errors_clear",   "Clear error buffer"),
    ("POST", "/api/logs/errors/export", "services.error_bus.handle_log_errors_export",  "Export errors"),

    # ── Log Service ──
    ("POST", "/api/logs/query",         "services.log.handle_log_query",                "Query logs"),
    ("GET",  "/api/logs/recent",        "services.log.handle_log_recent",               "Recent log entries"),
    ("GET",  "/api/logs/stats",         "services.log.handle_log_stats",                "Log statistics"),
    ("POST", "/api/logs/export",        "services.log.handle_log_export",               "Export logs"),

    # ── Config API ──
    ("POST", "/api/config",             "services.api_handlers_config.handle_config_list","List config"),
    ("POST", "/api/config/get",         "services.api_handlers_config.handle_config_get", "Get config value"),
    ("PUT",  "/api/config/set",         "services.api_handlers_config.handle_config_set", "Set config"),
    ("GET",  "/api/config/categories",  "services.api_handlers_config.handle_config_categories","List categories"),

    # ── File Editor ──
    ("POST", "/api/fs/edit",            "services.file_editor.handle_fs_edit",           "Semantic file edit"),
    ("POST", "/api/fs/batch_edit",      "services.file_editor.handle_fs_batch_edit",     "Batch edit"),
    ("POST", "/api/fs/history",         "services.file_editor.handle_fs_history",        "File history"),
    ("POST", "/api/fs/undo",            "services.file_editor.handle_fs_undo",           "Undo"),
    ("POST", "/api/fs/redo",            "services.file_editor.handle_fs_redo",           "Redo"),
    ("POST", "/api/fs/patch",           "services.file_editor.handle_fs_patch_create",   "Create patch"),
    ("POST", "/api/fs/patch/apply",     "services.file_editor.handle_fs_patch_apply",    "Apply patch"),
    ("POST", "/api/fs/patch/revert",    "services.file_editor.handle_fs_patch_revert",   "Revert patch"),
    ("POST", "/api/fs/patches",         "services.file_editor.handle_fs_patch_list",     "List patches"),
    ("POST", "/api/fs/patch/get",       "services.file_editor.handle_fs_patch_get",      "Get patch detail"),

    # ── Prompt Engine ──
    ("POST", "/api/prompt/build",       "l3.prompt_engine.handle_prompt_build",    "Build prompt"),
    ("POST", "/api/prompt/context",     "l3.prompt_engine.handle_prompt_context",  "Context assembly"),
    ("GET",  "/api/prompt/templates",   "l3.prompt_engine.handle_prompt_templates","List templates"),
    ("POST", "/api/prompt/template",    "l3.prompt_engine.handle_prompt_template_register","Register template"),

    # ── LSP Manager ──
    ("POST", "/api/lsp/diagnostics",    "services.lsp_manager.handle_lsp_diagnostics",   "File diagnostics"),
    ("POST", "/api/lsp/hover",          "services.lsp_manager.handle_lsp_hover",         "Hover info"),
    ("GET",  "/api/lsp/servers",        "services.lsp_manager.handle_lsp_servers",       "List LSP servers"),
    ("POST", "/api/lsp/start",          "services.lsp_manager.handle_lsp_start",         "Start LSP server"),
    ("POST", "/api/lsp/stop",           "services.lsp_manager.handle_lsp_stop",          "Stop LSP server"),
    ("POST", "/api/lsp/feedback",       "services.lsp_manager.handle_lsp_feedback",      "Post-edit feedback"),

    # ── SubAgent ──
    ("POST", "/api/subagent/dispatch",   "services.subagent_framework.handle_subagent_dispatch","Dispatch subagent"),
    ("POST", "/api/subagent/result",     "services.subagent_framework.handle_subagent_result",   "Get result"),
    ("POST", "/api/subagent/cancel",     "services.subagent_framework.handle_subagent_cancel",   "Cancel task"),
    ("POST", "/api/subagent/tasks",      "services.subagent_framework.handle_subagent_list",     "List tasks"),
    ("GET",  "/api/subagent/specs",      "services.subagent_framework.handle_subagent_specs",    "List specs"),
    ("POST", "/api/subagent/spec",       "services.subagent_framework.handle_subagent_spec_register","Register spec"),
    ("POST", "/api/subagent/merge",      "services.subagent_framework.handle_subagent_merge",    "Merge results"),

    # ── Search Engine ──
    ("POST", "/api/search",              "services.search_engine.handle_search",                 "Unified search"),
    ("POST", "/api/search/semantic",     "services.search_engine.handle_search_semantic",         "Semantic search"),
    ("POST", "/api/search/symbol",       "services.search_engine.handle_search_symbol",            "Symbol search"),
    ("POST", "/api/search/docs",         "services.search_engine.handle_search_docs",             "Doc search"),
    ("POST", "/api/search/docs/index",   "services.search_engine.handle_search_index_doc",         "Index doc"),

    # ── Session Export ──
    ("POST", "/api/session/export",             "services.session_export.handle_session_export",              "Export session"),
    ("POST", "/api/session/import",             "services.session_export.handle_session_import",              "Import session"),
    ("GET",  "/api/session/snapshots",          "services.session_export.handle_session_snapshots",            "List snapshots"),
    ("POST", "/api/session/snapshot",           "services.session_export.handle_session_snapshot_create",      "Create snapshot"),
    ("POST", "/api/session/snapshot/restore",   "services.session_export.handle_session_snapshot_restore",    "Restore snapshot"),
    ("POST", "/api/session/snapshot/delete",    "services.session_export.handle_session_snapshot_delete",     "Delete snapshot"),

    # ── SSE Bridge ──
    ("GET",  "/api/events",             "services.sse_bridge.handle_sse",                  "SSE event stream"),

    # ── Resource Buffer ──
    ("GET",  "/api/buffer/status",  "services.resource_buffer.api.handle_buffer_status",  "Buffer status"),
    ("POST", "/api/buffer/commit",  "services.resource_buffer.api.handle_buffer_commit",  "Commit buffer to disk"),
    ("POST", "/api/buffer/diff",    "services.resource_buffer.api.handle_buffer_diff",    "Show pending diff"),
    ("POST", "/api/buffer/discard", "services.resource_buffer.api.handle_buffer_discard", "Discard pending changes"),

    # Monitor (standalone functions from api_handlers_monitor.py)
    ("GET",  "/api/monitor/events",    "services.api_handlers_monitor.handle_monitor_events",     "Query monitor events"),
    ("GET",  "/api/monitor/stats",     "services.api_handlers_monitor.handle_monitor_stats",      "Monitor event statistics"),
    ("GET",  "/api/monitor/stream",    "services.api_handlers_monitor.handle_monitor_stream",     "SSE monitor event stream"),
    ("GET",  "/api/monitor/gate",      "services.api_handlers_monitor.handle_message_gate_list",  "List message gate rules"),
    ("POST", "/api/monitor/gate",      "services.api_handlers_monitor.handle_message_gate_set",   "Set message gate rule"),
    ("DELETE","/api/monitor/gate/",    "services.api_handlers_monitor.handle_message_gate_remove", "Remove message gate rule"),
]
