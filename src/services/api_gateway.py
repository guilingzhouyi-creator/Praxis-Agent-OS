"""API Gateway — HTTP/WebSocket interface for external tooling.

Bridges the Agent OS to the outside world via:
  - REST API (JSON over HTTP)
  - WebSocket (streaming events)
  - CLI commands via HTTP

Endpoints:
  POST /api/card          — Submit a card
  GET  /api/card/:id      — Get card status
  GET  /api/cards         — List cards
  GET  /api/health        — Kernel health
  GET  /api/processes     — List processes
  GET  /api/devices       — List devices
  GET  /api/settings      — Get settings
  POST /api/settings      — Set settings
  WS   /api/events        — Stream kernel events

Usage:
  from services.api_gateway import start_api
  start_api()  # default port from kernel.params (API_GATEWAY_DEFAULT_PORT)
  # or specify custom port:
  start_api(port=8080)  # custom port
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from kernel.params import ENV_API_TOKEN, API_GATEWAY_DEFAULT_PORT, API_CORS_ORIGIN, API_CORS_ALLOW_METHODS, API_CORS_ALLOW_HEADERS, API_GATEWAY_PORT, API_GATEWAY_HOST, API_MAX_BODY_BYTES
from .api_handlers import ApiHandlers

logger = logging.getLogger(__name__)


@dataclass
class Route:
    """API route entry — method + path pattern + handler.

    Path patterns:
      Exact: "/api/health"
      Wildcard: "/api/card/" → matches "/api/card/<id>"
    """
    method: str = "GET"          # "GET" | "POST"
    path: str = ""               # exact path or prefix (trailing / = prefix match)
    handler: Callable = lambda *a, **kw: {}
    description: str = ""


class ApiGateway(ApiHandlers):
    """HTTP API gateway — token auth, REST, WebSocket, extensible route registry."""

    def __init__(self, host: str = API_GATEWAY_HOST, port: int = API_GATEWAY_PORT,
                 auth_token: str = ""):
        self.host = host
        self.port = port
        self.auth_token = auth_token or os.environ.get(ENV_API_TOKEN, "")
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._routes: list[Route] = []
        self._register_defaults()

    def register_route(self, method: str, path: str,
                       handler: Callable, description: str = "") -> None:
        """Register a new API route. External code can call this to add endpoints.

        Args:
            method: "GET" or "POST"
            path: Exact path (e.g. "/api/health") or prefix (trailing "/" for wildcard)
            handler: Callable that takes (body|params) dict and returns a dict
            description: Human-readable description for the /api/endpoints listing
        """
        self._routes.append(Route(method=method, path=path,
                                  handler=handler, description=description))

    def _register_defaults(self) -> None:
        self.register_route("POST", "/api/card", self._submit_card, "Submit a card")
        self.register_route("POST", "/api/settings", self._set_settings, "Set settings")
        self.register_route("POST", "/api/card/batch", self._submit_batch, "Submit batch cards")
        self.register_route("POST", "/api/dispatch", self._sideload_dispatch, "Side-load dispatch")
        self.register_route("POST", "/api/cell/stop", self._cell_stop, "Emergency stop cell")
        self.register_route("POST", "/api/card/rollback", self._card_rollback, "Rollback card")
        self.register_route("POST", "/api/mcp/import", self._mcp_import, "Import MCP server")
        self.register_route("DELETE", "/api/mcp/servers", self._mcp_remove, "Remove MCP server")
        self.register_route("GET", "/api/mcp/servers", self._mcp_list, "List MCP servers")
        # CentralSecurity
        self.register_route("POST", "/api/security/check", self._security_check, "Check action against all gates")
        self.register_route("GET", "/api/security/stats", self._security_stats, "Security check statistics")
        # CentralMemory
        self.register_route("POST", "/api/memory/store", self._memory_store, "Store in memory ring")
        self.register_route("POST", "/api/memory/recall", self._memory_recall, "Recall from memory rings")
        self.register_route("GET", "/api/memory/stats", self._memory_stats, "Memory statistics")
        # CentralPlugin
        self.register_route("GET", "/api/plugins", self._plugin_list, "List installed plugins")
        self.register_route("POST", "/api/plugins/tool", self._plugin_install_tool, "Install tool plugin")
        self.register_route("DELETE", "/api/plugins", self._plugin_remove, "Remove plugin")
        self.register_route("POST", "/api/plugins/mcp", self._plugin_install_mcp, "Install MCP server as plugin")
        self.register_route("GET", "/api/plugins/stats", self._plugin_stats, "Plugin statistics")
        # Unified card types
        self.register_route("GET", "/api/card_types", self._card_types_list, "List card types")
        self.register_route("POST", "/api/card_types", self._card_types_register, "Register card type")
        self.register_route("POST", "/api/trust/check", self._trust_check, "Evaluate content trust")
        self.register_route("GET", "/api/trust/stats", self._trust_stats, "Content trust statistics")
        self.register_route("GET", "/api/session/state", self._session_state, "Get current session state (L3A/Direct)")
        self.register_route("POST", "/api/card_unified", self._card_unified_submit, "Submit unified card")
        self.register_route("POST", "/api/cards/plan", self._card_plan, "Get card execution plan")
        self.register_route("POST", "/api/cache", self._cache_stats, "Cache stats")
        self.register_route("POST", "/api/approvals", self._approval_respond, "Respond to approval")
        self.register_route("GET", "/api/health", self._health, "Kernel health")
        self.register_route("GET", "/api/cards", self._list_cards, "List cards")
        self.register_route("GET", "/api/card/", self._get_card, "Get card by ID")
        self.register_route("GET", "/api/processes", self._processes, "List processes")
        self.register_route("GET", "/api/devices", self._devices, "List devices")
        self.register_route("GET", "/api/settings", self._settings, "Get settings")
        self.register_route("GET", "/api/syscalls", self._syscalls, "List syscalls")
        self.register_route("GET", "/api/peers", self._peers, "List peers")
        self.register_route("GET", "/api/cell/liveness", self._cell_liveness, "Cell liveness check")
        self.register_route("GET", "/api/agent/reachable/", self._agent_reachable, "Agent session reachable")
        # CronScheduler
        self.register_route("GET", "/api/cron", self._cron_list, "List cron schedules")
        self.register_route("POST", "/api/cron", self._cron_add, "Add cron schedule")
        self.register_route("DELETE", "/api/cron", self._cron_remove, "Remove cron schedule")
        self.register_route("POST", "/api/agent/direct", self._agent_direct, "Start/continue direct session")
        self.register_route("POST", "/api/agent/direct/close", self._agent_direct_close, "Close direct session")
        self.register_route("GET", "/api/agents", self._agent_list, "List all agents (preselect)")
        self.register_route("GET", "/api/agent/select/", self._agent_select, "Select agent by id")
        self.register_route("POST", "/api/agent/select", self._agent_select_by, "Select agent by role/domain")
        self.register_route("POST", "/api/agent/preconnect", self._agent_preconnect, "Pre-connect verification")
        self.register_route("POST", "/api/agent/review", self._agent_review_message, "External LLM review message")
        self.register_route("POST", "/api/shell", self._shell_dispatch, "Shell command dispatch")
        self.register_route("GET", "/api/shell/autocomplete", self._shell_autocomplete, "Shell auto-complete hints")
        self.register_route("GET", "/api/shell/commands", self._shell_commands, "Shell available commands")
        self.register_route("GET", "/api/endpoints", self._list_endpoints, "List endpoints")
        self.register_route("GET", "/api/v1/tools", self._list_tools_v1, "List tools with locale support")
        self.register_route("GET", "/api/v1/locales", self._list_locales, "List available locales")
        self.register_route("GET", "/api/rollback/context", self._rollback_context, "Current rollback context")
        self.register_route("GET", "/api/card_gate/stats", self._card_gate_stats, "Card Gate stats")
        self.register_route("GET", "/api/pending", self._pending_list, "Pending queue list")
        self.register_route("POST", "/api/pending/approve", self._pending_approve, "Approve pending card")
        self.register_route("POST", "/api/pending/reject", self._pending_reject, "Reject pending card")
        self.register_route("POST", "/api/pending/escalate", self._pending_escalate, "Escalate to convention")
        self.register_route("POST", "/api/pending/priority", self._pending_priority, "Set pending priority")
        self.register_route("GET", "/api/pending/stats", self._pending_stats, "Pending queue stats")
        self.register_route("GET", "/api/card_gate/history", self._card_gate_history, "Card Gate approval history")
        self.register_route("GET", "/api/approvals/pending", self._gate_pending, "Card Gate pending")
        self.register_route("POST", "/api/approvals/respond", self._gate_respond, "Card Gate respond")
        self.register_route("GET", "/api/approvals", self._list_approvals, "List approvals")
        self.register_route("GET", "/api/tokens", self._token_stats, "Token stats")
        self.register_route("GET", "/api/tokens/cells", self._token_cells, "Token per Cell")
        self.register_route("GET", "/api/tokens/global", self._token_global, "Token global summary")
        self.register_route("GET", "/api/communication/stats", self._comm_stats, "Communication stats")
        self.register_route("GET", "/api/communication/recent", self._comm_recent, "Recent communication")
        self.register_route("GET", "/api/tools", self._tool_stats, "Tool stats")
        self.register_route("GET", "/api/loops", self._loop_stats, "Loop stats")
        self.register_route("GET", "/api/loops/recent", self._loops_recent, "Recent loops")
        self.register_route("GET", "/api/export", self._export_counter, "Export counter data")
        self.register_route("GET", "/api/bootstrap/status", self._bootstrap_status, "Check if bootstrap needed")
        self.register_route("GET", "/api/bootstrap/defaults", self._bootstrap_defaults, "Get default config")
        self.register_route("POST", "/api/bootstrap/apply", self._bootstrap_apply, "Apply config")
        self.register_route("GET", "/api/card/approval/", self._card_approval_trail, "Card approval trail")
        self.register_route("GET", "/api/card_gate/config", self._card_gate_config, "Card Gate config")
        self.register_route("POST", "/api/card_gate/config", self._card_gate_config_set, "Set Card Gate config")
        self.register_route("GET", "/api/metrics", self._export_metrics, "Export Prometheus metrics")
        self.register_route("GET", "/api/credentials", self._credential_status, "Credential vault status")
        self.register_route("POST", "/api/credentials", self._credential_set, "Set credential")
        self.register_route("DELETE", "/api/credentials", self._credential_delete, "Delete credential")
        self.register_route("GET", "/api/mode", self._tool_mode_get, "Get tool mode")
        self.register_route("PUT", "/api/mode", self._tool_mode_set, "Set tool mode (read|write|toggle)")

        # ── Error Bus routes (from error_bus.py) ──
        try:
            from services.error_bus import LOG_ROUTES
            for method, path, handler, desc in LOG_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("error_bus routes: %s", e)

        # ── Config API routes (config-driven placeholder API) ──
        try:
            from services.api_handlers_config import CONFIG_ROUTES
            for method, path, handler, desc in CONFIG_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("config routes: %s", e)

        # ── File Editor routes ──
        try:
            from services.file_editor import FS_ROUTES
            for method, path, handler, desc in FS_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("fs routes: %s", e)

        # ── Prompt Engine routes ──
        try:
            from services.prompt_engine import PROMPT_ROUTES
            for method, path, handler, desc in PROMPT_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("prompt routes: %s", e)

        # ── LSP Manager routes ──
        try:
            from services.lsp_manager import LSP_ROUTES
            for method, path, handler, desc in LSP_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("lsp routes: %s", e)

        # ── SubAgent Framework routes ──
        try:
            from services.subagent_framework import SUBAGENT_ROUTES
            for method, path, handler, desc in SUBAGENT_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("subagent routes: %s", e)

        # ── Search Engine routes ──
        try:
            from services.search_engine import SEARCH_ROUTES
            for method, path, handler, desc in SEARCH_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("search routes: %s", e)

        # ── Session Export routes ──
        try:
            from services.session_export import SESSION_ROUTES
            for method, path, handler, desc in SESSION_ROUTES:
                self.register_route(method, path, handler, desc)
        except Exception as e:
            logger.warning("session routes: %s", e)

        # ── SSE Bridge routes ──
        try:
            from services.sse_bridge import SSE_ROUTES, ensure_active
            for method, path, handler, desc in SSE_ROUTES:
                self.register_route(method, path, handler, desc)
            ensure_active()  # 激活 EventBus → SSE 广播
        except Exception as e:
            logger.warning("sse routes: %s", e)

    def _match_route(self, method: str, path: str) -> tuple[Callable, dict]:
        """Find matching route handler. Returns (handler, path_params)."""
        for r in self._routes:
            if r.method != method:
                continue
            if r.path.endswith("/"):
                if path.startswith(r.path.rstrip("/")):
                    return r.handler, {"id": path.split("/")[-1]}
            if path == r.path:
                return r.handler, {}
        return self._not_found, {}

    def _not_found(self, body: dict) -> dict:
        return {"error": "not found", "endpoints": self._list_endpoints()}

    def start(self) -> dict:
        """Start the API server in a background thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("API gateway started on %s:%d", self.host, self.port)
        return {"success": True, "host": self.host, "port": self.port}

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    def _run(self) -> None:
        """Run a simple HTTP server using only stdlib."""
        import http.server
        import urllib.parse

        class _Handler(http.server.BaseHTTPRequestHandler):
            gateway = self

            def log_message(self, fmt, *args):
                pass

            def _auth_ok(self) -> bool:
                import hmac
                if not self.gateway.auth_token:
                    return True
                received = self.headers.get("Authorization", "").replace("Bearer ", "")
                # Constant-time comparison to prevent timing attacks
                if len(received) != len(self.gateway.auth_token):
                    return False
                return hmac.compare_digest(received, self.gateway.auth_token)

            def _check_auth(self) -> bool:
                if not self._auth_ok():
                    self._json({"error": "unauthorized"}, 401)
                    return False
                return True

            def _json(self, data: Any, code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if length == 0:
                    return {}
                # Cap the body size to prevent unbounded memory allocation
                # via crafted Content-Length headers. Anything larger is
                # rejected before any bytes are buffered.
                if length > API_MAX_BODY_BYTES:
                    self._json({"error": "request body too large"}, 413)
                    return {}
                return json.loads(self.rfile.read(length))

            def _user_id(self) -> str:
                return self.headers.get("X-User-Id", "")

            def do_POST(self):
                if not self._check_auth():
                    return
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path.rstrip("/")
                body = self._read_body()
                body["_user_id"] = self._user_id()
                handler, params = self.gateway._match_route("POST", path)
                if params.get("id"):
                    body["_id"] = params["id"]
                self._json(handler(body))

            def do_GET(self):
                if not self._check_auth():
                    return
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path.rstrip("/")
                query = urllib.parse.parse_qs(parsed.query)

                # SSE 特殊处理：长连接 + text/event-stream
                if path == "/api/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
                    self.end_headers()
                    client = subscribe()
                    q = client["queue"]
                    try:
                        while True:
                            try:
                                event = q.get(timeout=30)
                                if event is None:
                                    break
                                line = f"data: {json.dumps(event, default=str)}\n\n"
                                self.wfile.write(line.encode())
                                self.wfile.flush()
                            except queue.Empty:
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        unsubscribe(client["client_id"])
                    return

                handler, params = self.gateway._match_route("GET", path)
                if params.get("id"):
                    body = {"_id": params["id"]}
                    body.update({k: v[0] for k, v in query.items()})
                else:
                    body = {k: v[0] for k, v in query.items()}
                self._json(handler(body))

            def do_DELETE(self):
                if not self._check_auth():
                    return
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path.rstrip("/")
                body = self._read_body()
                handler, params = self.gateway._match_route("DELETE", path)
                self._json(handler(body))

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", API_CORS_ORIGIN)
                self.send_header("Access-Control-Allow-Methods", API_CORS_ALLOW_METHODS)
                self.send_header("Access-Control-Allow-Headers", API_CORS_ALLOW_HEADERS)
                self.end_headers()

        try:
            addr = (self.host, self.port)
            self._server = http.server.HTTPServer(addr, _Handler)
            self._server.serve_forever()
        except OSError as e:
            logger.error("API gateway failed to start: %s", e)
        except Exception as e:
            logger.error("API gateway error: %s", e)

    # ── All handler methods inherited from ApiHandlers mixin ──


_gateway: ApiGateway | None = None


def start_api(host: str = API_GATEWAY_HOST, port: int = API_GATEWAY_PORT,
              auth_token: str = "") -> ApiGateway:
    global _gateway
    if _gateway is None:
        _gateway = ApiGateway(host, port, auth_token)
        _gateway.start()
    return _gateway


def stop_api() -> None:
    global _gateway
    if _gateway:
        _gateway.stop()
    _gateway = None


def load_routes_from_yaml(routes_cfg: list[dict]) -> dict:
    """Load API routes from a list of route dicts (from praxis.yaml api.routes).

    Each route dict:
      method: "GET" | "POST"
      path: "/api/v1/..."
      handler: "module.attr:subpath"  (dot path to a callable)
      description: "..."

    The handler string is resolved at load time:
      "services.cache_doc:get_store.get_content" → get_store().get_content
      "tools_archive:archive_search" → archive_search
    """
    gw = _gateway
    if not gw:
        return {"success": False, "error": "API gateway not started"}

    loaded = 0
    errors = []
    for entry in (routes_cfg or []):
        method = entry.get("method", "GET").upper()
        path = entry.get("path", "")
        handler_path = entry.get("handler", "")
        description = entry.get("description", "")
        if not path or not handler_path:
            errors.append(f"route missing path or handler: {entry}")
            continue

        try:
            handler = _resolve_handler(handler_path)
            gw.register_route(method, path, handler, description)
            loaded += 1
        except Exception as e:
            errors.append(f"route {method} {path}: {e}")

    if errors:
        logger.warning("load_routes: %d loaded, %d errors: %s", loaded, len(errors), errors)
    return {"success": True, "loaded": loaded, "errors": errors}


def _resolve_handler(path: str) -> callable:
    """Resolve 'module.attr:subattr' to a callable.

    Examples:
      "services.cache_doc:get_store.get_content"
        → import services.cache_doc → get_store().get_content
      "tools_archive:archive_search"
        → import tools_archive → archive_search
    """
    module_path, _, attr_path = path.partition(":")
    if not attr_path:
        raise ValueError(f"handler path must contain ':' — got '{path}'")

    import importlib
    mod = importlib.import_module(module_path)
    parts = attr_path.split(".")
    obj = mod
    for part in parts:
        obj = getattr(obj, part)
        if callable(obj):
            return obj
    if callable(obj):
        return obj
    raise ValueError(f"'{attr_path}' in {module_path} is not callable")
