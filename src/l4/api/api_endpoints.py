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
    # kebab-case (v2) and legacy snake-case both map to the approval domain —
    # the v2 migration renamed /api/card_gate/ → /api/v2/card-gate/, and
    # without the kebab entry these endpoints fall through to "card".
    "/api/card-gate": "approval", "/api/card_gate": "approval",
    "/api/approvals": "approval", "/api/pending": "approval",
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
    "/api/providers": "provider", "/api/model-spec": "provider",
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
    "/api/auth": "security", "/api/ws": "system",
}

# ── 7 work-domain groups (AGENTS.md parallel-collaboration domains) ───────────
# Fine-grained domain → top-level work group.  Every endpoint's `group` field
# is derived here; the fine `domain` is kept for sub-grouping and future
# per-group routing prefixes (/api/v2/<group>/...).
_DOMAIN_GROUP: dict[str, str] = {
    # A — bridge/shell (user-facing surface)
    "system": "shell", "lifecycle": "shell", "config": "shell",
    "shell": "shell", "comm": "shell", "sse": "shell", "monitor": "shell",
    # K — kernel (security / constitution / credentials)
    "security": "kernel", "constitution": "kernel", "credential": "kernel",
    "token": "kernel", "trust": "kernel", "rollback": "kernel",
    # M — memory (rings / search / records / logs)
    "memory": "memory", "search": "memory", "records": "memory",
    "log": "memory", "cache": "memory",
    # S — sessions (L3A / discussion / session lifecycle)
    "session": "sessions", "l3a": "sessions", "discussion": "sessions",
    # T — tools (filesystem / LSP / prompt / diff / skills)
    "tool": "tools", "fs": "tools", "lsp": "tools", "prompt": "tools",
    "diff": "tools", "skill": "tools", "buffer": "tools", "loop": "tools",
    # C — card-cell (cards / approvals / pending / cell / cluster)
    "card": "card-cell", "approval": "card-cell", "cell": "card-cell",
    "cluster": "card-cell", "dispatch": "card-cell",
    # B — bus-services (MCP / plugins / subagents / providers / cron)
    "mcp": "bus-services", "plugin": "bus-services", "subagent": "bus-services",
    "scout": "bus-services", "r4": "bus-services", "provider": "bus-services",
    "cron": "bus-services", "stats": "bus-services", "agent": "bus-services",
    # fallback
    "misc": "misc",
}

_VERSION_PREFIXES = ("/api/v1/", "/api/v2/", "/api/v3/")


def _strip_version(path: str) -> str:
    """Strip a leading version prefix so classification ignores versioning.

    ``/api/v2/providers`` → ``/api/providers``; unversioned paths pass through.
    """
    for prefix in _VERSION_PREFIXES:
        if path.startswith(prefix):
            return "/api/" + path[len(prefix):]
    return path


def _infer_domain(path: str) -> str:
    """Infer the functional domain from the path prefix (basis for naming normalization).

    Version prefixes (``/api/v1/``, ``/api/v2/``) are stripped before matching
    so versioned endpoints classify identically to their unversioned siblings
    (previously all ``/api/v2/*`` fell through to ``misc``).
    """
    stripped = _strip_version(path)
    for prefix, domain in sorted(_DOMAIN_BY_PREFIX.items(), key=lambda kv: -len(kv[0])):
        if stripped.startswith(prefix):
            return domain
    return "misc"


def _infer_group(domain: str) -> str:
    """Map a fine-grained domain to its 7-work-domain group."""
    return _DOMAIN_GROUP.get(domain, "misc")


@dataclass(frozen=True)
class ApiEndpoint:
    """A single registered API endpoint entry.

    ``group`` is derived (property) from ``domain`` via the 7-work-domain
    mapping — it is not a stored field, so positional construction elsewhere
    (scattered/outbound lists) is unaffected.
    """

    method: str
    path: str
    handler_ref: str = ""
    description: str = ""
    domain: str = ""            # fine-grained functional domain (e.g. "skill")
    source: str = ""            # original registration source (module path or "api_routes")
    kind: str = "http"          # http=gateway inbound endpoint; outbound=external protocol endpoint

    @property
    def group(self) -> str:
        """7-work-domain group derived from the fine-grained domain."""
        return _infer_group(self.domain)

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
    ApiEndpoint("POST", "/api/v2/subagent/dispatch", "l3.agent.subagent_framework.handle_subagent_dispatch", "Dispatch subagent (@mention or spec+prompt)", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/v2/subagent/result", "l3.agent.subagent_framework.handle_subagent_result", "Get subagent task result", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/v2/subagent/cancel", "l3.agent.subagent_framework.handle_subagent_cancel", "Cancel subagent task", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/v2/subagent/tasks", "l3.agent.subagent_framework.handle_subagent_list", "List subagent tasks", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("GET", "/api/v2/subagent/specs", "l3.agent.subagent_framework.handle_subagent_specs", "List subagent specs", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/v2/subagent/spec", "l3.agent.subagent_framework.handle_subagent_spec_register", "Register subagent spec", "subagent", "l3.agent.subagent_framework", "http"),
    ApiEndpoint("POST", "/api/v2/subagent/merge", "l3.agent.subagent_framework.handle_subagent_merge", "Merge multiple subagent results", "subagent", "l3.agent.subagent_framework", "http"),

    # logs (formerly LOG_SERVICE_ROUTES @ l3/bus/log.py)
    ApiEndpoint("POST", "/api/v2/logs/query", "l3.bus.log.handle_log_query", "Query logs with filters", "log", "l3.bus.log", "http"),
    ApiEndpoint("GET", "/api/v2/logs/recent", "l3.bus.log.handle_log_recent", "Recent log entries", "log", "l3.bus.log", "http"),
    ApiEndpoint("GET", "/api/v2/logs/stats", "l3.bus.log.handle_log_stats", "Log statistics", "log", "l3.bus.log", "http"),
    ApiEndpoint("POST", "/api/v2/logs/export", "l3.bus.log.handle_log_export", "Export logs to JSON", "log", "l3.bus.log", "http"),

    # fs (formerly FS_ROUTES @ l3/services/file_editor.py)
    ApiEndpoint("POST", "/api/v2/fs/edit", "l3.services.file_editor.handle_fs_edit", "Semantic file edit (search/replace)", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/batch-edit", "l3.services.file_editor.handle_fs_batch_edit", "Atomic batch multi-file edit", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/history", "l3.services.file_editor.handle_fs_history", "File operation history", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/undo", "l3.services.file_editor.handle_fs_undo", "Undo file operation", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/redo", "l3.services.file_editor.handle_fs_redo", "Redo file operation", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/patch", "l3.services.file_editor.handle_fs_patch_create", "Create patch from history", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/patch/apply", "l3.services.file_editor.handle_fs_patch_apply", "Apply patch", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/patch/revert", "l3.services.file_editor.handle_fs_patch_revert", "Revert patch", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/patches", "l3.services.file_editor.handle_fs_patch_list", "List all patches", "fs", "l3.services.file_editor", "http"),
    ApiEndpoint("POST", "/api/v2/fs/patch/get", "l3.services.file_editor.handle_fs_patch_get", "Get patch detail", "fs", "l3.services.file_editor", "http"),

    # prompt (formerly PROMPT_ROUTES @ l3/services/prompt_engine.py)
    ApiEndpoint("POST", "/api/v2/prompt/build", "l3.services.prompt_engine.handle_prompt_build", "Build full prompt with context assembly", "prompt", "l3.services.prompt_engine", "http"),
    ApiEndpoint("POST", "/api/v2/prompt/context", "l3.services.prompt_engine.handle_prompt_context", "Assemble context only (preview)", "prompt", "l3.services.prompt_engine", "http"),
    ApiEndpoint("GET", "/api/v2/prompt/templates", "l3.services.prompt_engine.handle_prompt_templates", "List prompt templates", "prompt", "l3.services.prompt_engine", "http"),
    ApiEndpoint("POST", "/api/v2/prompt/template", "l3.services.prompt_engine.handle_prompt_template_register", "Register custom template", "prompt", "l3.services.prompt_engine", "http"),

    # session (formerly SESSION_ROUTES @ l3/services/session_export.py)
    ApiEndpoint("POST", "/api/v2/session/export", "l3.services.session_export.handle_session_export", "Export session as JSON", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/v2/session/import", "l3.services.session_export.handle_session_import", "Import session from JSON", "session", "l3.services.session_export", "http"),
    ApiEndpoint("GET", "/api/v2/session/snapshots", "l3.services.session_export.handle_session_snapshots", "List snapshots", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/v2/session/snapshot", "l3.services.session_export.handle_session_snapshot_create", "Create snapshot", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/v2/session/snapshot/restore", "l3.services.session_export.handle_session_snapshot_restore", "Restore snapshot", "session", "l3.services.session_export", "http"),
    ApiEndpoint("POST", "/api/v2/session/snapshot/delete", "l3.services.session_export.handle_session_snapshot_delete", "Delete snapshot", "session", "l3.services.session_export", "http"),

    # config (formerly CONFIG_ROUTES @ l4/api_handlers/api_handlers_config.py)
    ApiEndpoint("POST", "/api/v2/config", "l4.api_handlers.api_handlers_config.handle_config_list", "List all config (optional filter: {category})", "config", "l4.api_handlers.api_handlers_config", "http"),
    ApiEndpoint("POST", "/api/v2/config/get", "l4.api_handlers.api_handlers_config.handle_config_get", "Get config value by key", "config", "l4.api_handlers.api_handlers_config", "http"),
    ApiEndpoint("PUT", "/api/v2/config/set", "l4.api_handlers.api_handlers_config.handle_config_set", "Set config override at runtime", "config", "l4.api_handlers.api_handlers_config", "http"),

    # lsp (formerly LSP_ROUTES @ l4/lsp/lsp_manager.py)
    ApiEndpoint("POST", "/api/v2/lsp/diagnostics", "l4.lsp.lsp_manager.handle_lsp_diagnostics", "Get file diagnostics", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/v2/lsp/hover", "l4.lsp.lsp_manager.handle_lsp_hover", "Get hover info", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("GET", "/api/v2/lsp/servers", "l4.lsp.lsp_manager.handle_lsp_servers", "List LSP server status", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/v2/lsp/start", "l4.lsp.lsp_manager.handle_lsp_start", "Start LSP server", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/v2/lsp/stop", "l4.lsp.lsp_manager.handle_lsp_stop", "Stop LSP server", "lsp", "l4.lsp.lsp_manager", "http"),
    ApiEndpoint("POST", "/api/v2/lsp/feedback", "l4.lsp.lsp_manager.handle_lsp_feedback", "Post-edit feedback loop", "lsp", "l4.lsp.lsp_manager", "http"),

    # search (formerly SEARCH_ROUTES @ l4/search/search_engine.py)
    ApiEndpoint("POST", "/api/v2/search", "l4.search.search_engine.handle_search", "Unified search (auto-select mode)", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/v2/search/semantic", "l4.search.search_engine.handle_search_semantic", "Semantic code search", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/v2/search/symbol", "l4.search.search_engine.handle_search_symbol", "Symbol search (AST-based)", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/v2/search/docs", "l4.search.search_engine.handle_search_docs", "API documentation search", "search", "l4.search.search_engine", "http"),
    ApiEndpoint("POST", "/api/v2/search/docs/index", "l4.search.search_engine.handle_search_index_doc", "Index custom API doc", "search", "l4.search.search_engine", "http"),

    # sse (formerly SSE_ROUTES @ l4/sse/sse_bridge.py)
    ApiEndpoint("GET", "/api/v2/events", "l4.sse.sse_bridge.handle_sse", "SSE event stream (EventBus over HTTP)", "sse", "l4.sse.sse_bridge", "http"),
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

# ── Public group catalogue (for consumers / docs / future /api/v2/<group>/) ─────
DOMAIN_GROUPS: tuple[str, ...] = (
    "shell", "kernel", "memory", "sessions", "tools", "card-cell", "bus-services", "misc",
)


def get_endpoints(domain: str = "", group: str = "",
                  source: str = "", kind: str = "") -> list[ApiEndpoint]:
    """Filter the manifest by domain / group / source / kind."""
    return [e for e in ENDPOINT_MANIFEST
            if (not domain or e.domain == domain)
            and (not group or e.group == group)
            and (not source or e.source == source)
            and (not kind or e.kind == kind)]


def register_domain(domain: str, group: str) -> dict:
    """Register a new fine-grained domain under a 7-work-domain group.

    Extension point: new endpoint families can be added at runtime without
    editing ``_DOMAIN_BY_PREFIX`` — just declare the domain once here and
    pass it explicitly to ``register_endpoint(domain=...)``.
    """
    domain = domain.strip().lower()
    group = group.strip().lower()
    _DOMAIN_GROUP.setdefault(domain, group)
    return {"success": True, "domain": domain, "group": group,
            "groups": sorted(set(_DOMAIN_GROUP.values()))}


def register_group(name: str) -> dict:
    """Register a new top-level work-domain group (rarely needed)."""
    name = name.strip().lower()
    if name not in _DOMAIN_GROUP.values():
        # Give every domain a fallback mapping to the new group only when
        # explicitly requested by the caller via register_domain.
        _DOMAIN_GROUP.setdefault(name, name)
    return {"success": True, "group": name, "groups": sorted(set(_DOMAIN_GROUP.values()))}


def register_endpoint(method: str, path: str, handler_ref: str = "",
                      description: str = "", domain: str = "",
                      source: str = "", kind: str = "http") -> ApiEndpoint:
    """Register a new endpoint (extension point for the unified naming convention).

    ``domain`` defaults to ``_infer_domain(path)``; the 7-work-domain ``group``
    is derived automatically from ``domain`` via ``_DOMAIN_GROUP``.  Unknown
    domains are auto-registered under the ``misc`` group — pass an explicit
    ``domain=`` (after ``register_domain``) to control the group.
    """
    resolved_domain = (domain or _infer_domain(path)).strip().lower()
    if resolved_domain not in _DOMAIN_GROUP:
        _DOMAIN_GROUP[resolved_domain] = "misc"
    ep = ApiEndpoint(method=method, path=path, handler_ref=handler_ref,
                     description=description,
                     domain=resolved_domain,
                     source=source, kind=kind)
    ENDPOINT_MANIFEST.append(ep)
    return ep


def validate() -> dict:
    """Validate the manifest: no duplicates in the central table + all scattered endpoints merged in.

    Also enforces naming-style rules that the unified prefix convention
    requires (see docs/architecture/overview.md):
      - no snake_case path segments (use kebab-case)
      - no legacy trailing-slash parameter style (use {param})
      - no duplicate (method, path) pairs anywhere in the manifest
      - classification coverage — misc should be (near) empty
    """
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

    # 3) classification coverage — misc should be (near) empty
    misc_paths = sorted({f"{e.method} {e.path}" for e in ENDPOINT_MANIFEST if e.domain == "misc"})
    if len(misc_paths) > 1:
        issues.append(f"{len(misc_paths)} unclassified endpoints (domain=misc): {misc_paths[:8]}...")

    # 4) naming style — snake_case path segments (unified prefix uses kebab-case);
    #    {param} placeholders are exempt — their names mirror handler keyword
    #    args (e.g. session_id) and are not URL path segments.
    snake_paths = sorted({f"{e.method} {e.path}" for e in ENDPOINT_MANIFEST
                          if any("_" in seg for seg in e.path.strip("/").split("/")
                                 if seg and not (seg.startswith("{") and seg.endswith("}")))})
    if snake_paths:
        issues.append(f"snake_case path segments (use kebab-case): {snake_paths[:10]}...")

    # 5) naming style — trailing-slash parameter routes (unified prefix uses {param})
    slash_paths = sorted({f"{e.method} {e.path}" for e in ENDPOINT_MANIFEST
                          if e.path.endswith("/")})
    if slash_paths:
        issues.append(f"trailing-slash parameter style (use {{param}}): {slash_paths[:10]}...")

    # 6) group consistency — every domain must map to a known 7-work-domain group
    unknown_groups = sorted({e.group for e in ENDPOINT_MANIFEST
                             if e.group not in DOMAIN_GROUPS})
    if unknown_groups:
        issues.append(f"unknown domain groups (not in {DOMAIN_GROUPS}): {unknown_groups}")

    return {"ok": not issues, "issues": issues, "total": len(ENDPOINT_MANIFEST),
            "central": len(_CENTRAL), "scattered": len(_SCATTERED),
            "outbound": len(_OUTBOUND), "misc": len(misc_paths)}


def summary() -> dict:
    """Count by functional domain and 7-work-domain group (reference for naming normalization)."""
    domains: dict[str, int] = {}
    groups: dict[str, int] = {}
    for e in ENDPOINT_MANIFEST:
        domains[e.domain] = domains.get(e.domain, 0) + 1
        groups[e.group] = groups.get(e.group, 0) + 1
    unique_http = {(e.method, e.path) for e in ENDPOINT_MANIFEST if e.kind == "http"}
    return {"total": len(ENDPOINT_MANIFEST),
            "unique_http": len(unique_http),
            "central": len(_CENTRAL),
            "scattered": len(_SCATTERED),
            "outbound": len(_OUTBOUND),
            "domains": dict(sorted(domains.items())),
            "groups": dict(sorted(groups.items()))}


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
