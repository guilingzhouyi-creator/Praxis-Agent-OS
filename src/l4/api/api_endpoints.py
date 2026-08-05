"""API endpoint manifest — centralized, single source of truth for all API endpoints.

Background
----------
- Inbound HTTP routing is registered from ``api_routes.API_ROUTES`` (loaded by the API gateway).
- Historically, 9 service modules maintained duplicate ``*_ROUTES`` lists (SUBAGENT_ROUTES /
  LOG_SERVICE_ROUTES / FS_ROUTES / PROMPT_ROUTES / SESSION_ROUTES / CONFIG_ROUTES /
  LSP_ROUTES / SEARCH_ROUTES / SSE_ROUTES, 46 entries total, all with zero consumers).
  These scattered lists were consolidated into this manifest in 2026-08 and the original
  definitions have been removed.
- This manifest also registers **outbound protocol endpoints** (card registry
  ``/api/v1/cards/*``, MCP ``/tools/*``) to provide a complete basis for future
  unified naming normalization.

Usage
-----
    from l4.api.api_endpoints import ENDPOINT_MANIFEST, get_endpoints, register_endpoint
    python -m l4.api.api_endpoints      # print the full manifest
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# ── Central routes (registration source of truth) ────────────────────────────────────
from .api_routes import API_ROUTES  # noqa: F401  (keep re-export for imports)

# ── Domain inference (classification for naming normalization) ────────────────────────────────────────
_DOMAIN_BY_PREFIX: dict[str, str] = {
    "/api/health": "system", "/api/processes": "system", "/api/devices": "system",
    "/api/peers": "system", "/api/syscalls": "system", "/api/endpoints": "system",
    "/api/mode": "system", "/api/export": "stats", "/api/metrics": "stats",
    "/api/card": "card", "/api/cards": "card", "/api/dispatch": "card",
    "/api/card_gate": "approval", "/api/approvals": "approval", "/api/pending": "approval",
    "/api/agent": "agent", "/api/agents": "agent",
    "/api/settings": "config", "/api/config": "config",
    "/api/security": "security", "/api/trust": "security",
    "/api/memory": "memory",
    "/api/shell": "shell",
    "/api/mcp": "mcp",
    "/api/plugins": "plugin",
    "/api/commands": "shell",
    "/api/tools": "tool", "/api/tokens": "token", "/api/loops": "loop",
    "/api/constitution": "constitution", "/api/discussion": "discussion",
    "/api/providers": "provider", "/api/model-spec": "provider", "/api/v2/model-spec": "provider",
    "/api/subagent": "subagent", "/api/scout": "scout", "/api/r4": "r4",
    "/api/l3a": "l3a",
    "/api/skills": "skill",
    "/api/convention": "convention", "/api/stats": "stats", "/api/records": "records",
    "/api/communication": "comm", "/api/cron": "cron", "/api/credentials": "credential",
    "/api/bootstrap": "lifecycle", "/api/boot": "lifecycle", "/api/shutdown": "lifecycle",
    "/api/reboot": "lifecycle", "/api/reload": "lifecycle", "/api/reset": "lifecycle",
    "/api/diff": "diff", "/api/rollback": "rollback", "/api/session": "session",
    "/api/logs": "log", "/api/errors": "log",
    "/api/lsp": "lsp", "/api/search": "search", "/api/prompt": "prompt",
    "/api/fs": "fs", "/api/buffer": "buffer", "/api/events": "sse",
    "/api/loop": "loop", "/api/monitor": "monitor", "/api/cell": "cell",
    "/api/cluster": "cluster", "/api/cache": "cache",
    "/api/card_types": "card", "/api/card_unified": "card", "/api/cards/plan": "card",
}


def _infer_domain(path: str) -> str:
    """Infer the functional domain from the path prefix (basis for naming normalization)."""
    for prefix, domain in sorted(_DOMAIN_BY_PREFIX.items(), key=lambda kv: -len(kv[0])):
        if path.startswith(prefix):
            return domain
    return "misc"


@dataclass(frozen=True)
class ApiEndpoint:
    """A single registered API endpoint entry."""

    method: str
    path: str
    handler_ref: str = ""
    description: str = ""
    domain: str = ""
    source: str = ""            # original registration source (module path or "api_routes")
    kind: str = "http"          # http=gateway inbound endpoint; outbound=external protocol endpoint

    def to_tuple(self) -> tuple[str, str, str, str]:
        """Convert back to the 4-tuple (method, path, handler_ref, description) used by api_routes."""
        return (self.method, self.path, self.handler_ref, self.description)


# ── Central routes auto-merged into manifest ───────────────────────────────────────────────────
_CENTRAL: list[ApiEndpoint] = [
    ApiEndpoint(method=m, path=p, handler_ref=h, description=d,
                domain=_infer_domain(p), source="api_routes", kind="http")
    for m, p, h, d in API_ROUTES
]

# ── Consolidated scattered routes (formerly the *_ROUTES dead lists in service modules) ──────────────────
_SCATTERED: list[ApiEndpoint] = [
    # subagent (formerly SUBAGENT_ROUTES @ l3/agent/subagent_framework.py)
    ApiEndpoint("POST", "/api/subagent/dispatch", "l3.agent.subagent_framework.handle_subagent_dispatch", "Dispatch subagent (@mention or spec+prompt)", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/subagent/result", "l3.agent.subagent_framework.handle_subagent_result", "Get subagent task result", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/subagent/cancel", "l3.agent.subagent_framework.handle_subagent_cancel", "Cancel subagent task", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/subagent/tasks", "l3.agent.subagent_framework.handle_subagent_list", "List subagent tasks", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("GET", "/api/subagent/specs", "l3.agent.subagent_framework.handle_subagent_specs", "List subagent specs", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/subagent/spec", "l3.agent.subagent_framework.handle_subagent_spec_register", "Register subagent spec", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/subagent/merge", "l3.agent.subagent_framework.handle_subagent_merge", "Merge multiple subagent results", "subagent", "l3.agent.subagent_framework", "http"),

    # logs (formerly LOG_SERVICE_ROUTES @ l3/bus/log.py)
    ApiEndpoint("POST", "/api/logs/query", "l3.bus.log.handle_log_query", "Query logs with filters", "log", "l3.bus.log", "http"),
    ApiEndpoint("GET", "/api/logs/recent", "l3.bus.log.handle_log_recent", "Recent log entries", "log", "l3.bus.log", "http"),
    ApiEndpoint("GET", "/api/logs/stats", "l3.bus.log.handle_log_stats", "Log statistics", "log", "l3.bus.log", "http"),
    ApiEndpoint("POST", "/api/logs/export", "l3.bus.log.handle_log_export", "Export logs to JSON", "log", "l3.bus.log", "http"),

    # fs (formerly FS_ROUTES @ l3/services/file_editor.py)
    ApiEndpoint("POST", "/api/fs/edit", "l3.services.file_editor.handle_fs_edit", "Semantic file edit (search/replace)", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/batch_edit", "l3.services.file_editor.handle_fs_batch_edit", "Atomic batch multi-file edit", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/history", "l3.services.file_editor.handle_fs_history", "File operation history", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/undo", "l3.services.file_editor.handle_fs_undo", "Undo file operation", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/redo", "l3.services.file_editor.handle_fs_redo", "Redo file operation", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/patch", "l3.services.file_editor.handle_fs_patch_create", "Create patch from history", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/patch/apply", "l3.services.file_editor.handle_fs_patch_apply", "Apply patch", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/patch/revert", "l3.services.file_editor.handle_fs_patch_revert", "Revert patch", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/patches", "l3.services.file_editor.handle_fs_patch_list", "List all patches", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/fs/patch/get", "l3.services.file_editor.handle_fs_patch_get", "Get patch detail", "fs", "l3.services.file_editor", "http"),

    # prompt (formerly PROMPT_ROUTES @ l3/services/prompt_engine.py)
    ApiEndpoint("POST", "/api/prompt/build", "l3.services.prompt_engine.handle_prompt_build", "Build full prompt with context assembly", "prompt", "l3.services.prompt_engine", "http"),
    ApiEndpoint("POST", "/api/prompt/context", "l3.services.prompt_engine.handle_prompt_context", "Assemble context only (preview)", "prompt", "l3.services.prompt_engine", "http"),
    ApiEndpoint("GET", "/api/prompt/templates", "l3.services.prompt_engine.handle_prompt_templates", "List prompt templates", "prompt", "l3.services.prompt_engine", "http"),
    ApiEndpoint("POST", "/api/prompt/template", "l3.services.prompt_engine.handle_prompt_template_register", "Register custom template", "prompt", "l3.services.prompt_engine", "http"),

    # session (formerly SESSION_ROUTES @ l3/services/session_export.py)
    ApiEndpoint("POST", "/api/session/export", "l3.services.session_export.handle_session_export", "Export session as JSON", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/session/import", "l3.services.session_export.handle_session_import", "Import session from JSON", "session", "l3.services.session_export", "http"),
    ApiEndpoint("GET", "/api/session/snapshots", "l3.services.session_export.handle_session_snapshots", "List snapshots", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/session/snapshot", "l3.services.session_export.handle_session_snapshot_create", "Create snapshot", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/session/snapshot/restore", "l3.services.session_export.handle_session_snapshot_restore", "Restore snapshot", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/session/snapshot/delete", "l3.services.session_export.handle_session_snapshot_delete", "Delete snapshot", "session", "l3.services.session_export", "http"),

    # config (formerly CONFIG_ROUTES @ l4/api_handlers/api_handlers_config.py)
    ApiEndpoint("POST", "/api/config", "l4.api_handlers.api_handlers_config.handle_config_list", "List all config (optional filter: {category})", "config", "l4.api_handlers.api_handlers_config", "http"),
    ApiEndpoint("POST", "/api/config/get", "l4.api_handlers.api_handlers_config.handle_config_get", "Get config value by key", "config", "l4.api_handlers.api_handlers_config", "http"),
    ApiEndpoint("PUT", "/api/config/set", "l4.api_handlers.api_handlers_config.handle_config_set", "Set config override at runtime", "config", "l4.api_handlers.api_handlers_config", "http"),

    # lsp (formerly LSP_ROUTES @ l4/lsp/lsp_manager.py)
    ApiEndpoint("POST", "/api/lsp/diagnostics", "l4.lsp.lsp_manager.handle_lsp_diagnostics", "Get file diagnostics", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/lsp/hover", "l4.lsp.lsp_manager.handle_lsp_hover", "Get hover info", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("GET", "/api/lsp/servers", "l4.lsp.lsp_manager.handle_lsp_servers", "List LSP server status", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/lsp/start", "l4.lsp.lsp_manager.handle_lsp_start", "Start LSP server", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/lsp/stop", "l4.lsp.lsp_manager.handle_lsp_stop", "Stop LSP server", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/lsp/feedback", "l4.lsp.lsp_manager.handle_lsp_feedback", "Post-edit feedback loop", "lsp", "l4.lsp.lsp_manager", "http"),

    # search (formerly SEARCH_ROUTES @ l4/search/search_engine.py)
    ApiEndpoint("POST", "/api/search", "l4.search.search_engine.handle_search", "Unified search (auto-select mode)", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/search/semantic", "l4.search.search_engine.handle_search_semantic", "Semantic code search", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/search/symbol", "l4.search.search_engine.handle_search_symbol", "Symbol search (AST-based)", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/search/docs", "l4.search.search_engine.handle_search_docs", "API documentation search", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/search/docs/index", "l4.search.search_engine.handle_search_index_doc", "Index custom API doc", "search", "l4.search.search_engine", "http"),

    # sse (formerly SSE_ROUTES @ l4/sse/sse_bridge.py)
    ApiEndpoint("GET", "/api/events", "l4.sse.sse_bridge.handle_sse", "SSE event stream (EventBus over HTTP)", "sse", "l4.sse.sse_bridge", "http"),
]

# ── Outbound protocol endpoints (external API points called by clients) ────────────────────────────────
_OUTBOUND: list[ApiEndpoint] = [
    # Card registry protocol @ l3/card/card_registry_protocol.py
    ApiEndpoint("GET", "{base}/api/v1/cards", "", "List available card types", "registry", "l3.card.card_registry_protocol", "outbound"),
    ApiEndpoint("GET", "{base}/api/v1/cards/{name}", "", "Download card definition (.yaml)", "registry", "l3.card.card_registry_protocol", "outbound"),
    ApiEndpoint("POST", "{base}/api/v1/cards/publish", "", "Publish a card definition", "registry", "l3.card.card_registry_protocol", "outbound"),
    ApiEndpoint("GET", "{base}/api/v1/cards/search?q=", "", "Search card types", "registry", "l3.card.card_registry_protocol", "outbound"),
    # MCP client protocol @ l4/mcp_bridge.py
    ApiEndpoint("GET", "{endpoint}/tools/list", "", "MCP tools/list", "mcp", "l4.mcp_bridge.McpClient", "outbound"),
    ApiEndpoint("POST", "{endpoint}/tools/call", "", "MCP tools/call", "mcp", "l4.mcp_bridge.McpClient", "outbound"),
    ApiEndpoint("GET", "{endpoint}/ping", "", "MCP ping", "mcp", "l4.mcp_bridge.McpClient", "outbound"),
]

# ── Full manifest ────────────────────────────────────────────────────────────────
ENDPOINT_MANIFEST: list[ApiEndpoint] = _CENTRAL + _SCATTERED + _OUTBOUND


def get_endpoints(domain: str = "", source: str = "", kind: str = "") -> list[ApiEndpoint]:
    """Filter the manifest by domain / source / kind."""
    return [e for e in ENDPOINT_MANIFEST
            if (not domain or e.domain == domain)
            and (not source or e.source == source)
            and (not kind or e.kind == kind)]


def register_endpoint(method: str, path: str, handler_ref: str = "",
                      description: str = "", domain: str = "",
                      source: str = "", kind: str = "http") -> ApiEndpoint:
    """Register a new endpoint (extension point for the upcoming unified naming convention)."""
    ep = ApiEndpoint(method=method, path=path, handler_ref=handler_ref,
                     description=description,
                     domain=domain or _infer_domain(path),
                     source=source, kind=kind)
    ENDPOINT_MANIFEST.append(ep)
    return ep


def validate() -> dict:
    """Validate the manifest: no duplicates in the central table + all scattered endpoints merged in."""
    issues: list[str] = []
    # 1) no duplicates allowed inside the central table (registration source of truth)
    seen: set[tuple[str, str]] = set()
    for m, p, _, _ in API_ROUTES:
        key = (m, p)
        if key in seen:
            issues.append(f"duplicate in API_ROUTES: {m} {p}")
        seen.add(key)

    # 2) consolidated scattered endpoints must exist in the central table (prevent drift)
    central_keys = {(m, p) for m, p, _, _ in API_ROUTES}
    for e in _SCATTERED:
        if (e.method, e.path) not in central_keys:
            issues.append(f"scattered endpoint not in API_ROUTES: {e.method} {e.path} "
                          f"(source={e.source})")
    return {"ok": not issues, "issues": issues, "total": len(ENDPOINT_MANIFEST),
            "central": len(_CENTRAL), "scattered": len(_SCATTERED),
            "outbound": len(_OUTBOUND)}


def summary() -> dict:
    """Count by functional domain (reference for naming normalization)."""
    domains: dict[str, int] = {}
    for e in ENDPOINT_MANIFEST:
        domains[e.domain] = domains.get(e.domain, 0) + 1
    unique_http = {(e.method, e.path) for e in ENDPOINT_MANIFEST if e.kind == "http"}
    return {"total": len(ENDPOINT_MANIFEST),
            "unique_http": len(unique_http),
            "central": len(_CENTRAL),
            "scattered": len(_SCATTERED),
            "outbound": len(_OUTBOUND),
            "domains": dict(sorted(domains.items()))}


def _dump() -> None:
    print("=== Praxis API endpoint manifest (centralized) ===")
    print(f"Total: {len(ENDPOINT_MANIFEST)}"
          f" (central {len(_CENTRAL)} / consolidated-scattered {len(_SCATTERED)} / outbound {len(_OUTBOUND)})")
    print()
    for e in ENDPOINT_MANIFEST:
        disp = e.path
        if disp.endswith("/"):
            disp += "<id>"
        print(f"{e.method:6s} {disp:38s} [{e.domain:12s}] {e.kind:8s} {e.description} ({e.source})")


if __name__ == "__main__":
    _dump()
    sys.exit(0 if validate()["ok"] else 1)
