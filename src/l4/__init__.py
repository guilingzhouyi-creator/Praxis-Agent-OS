"""Bridge layer — API gateway, LLM engine, sandbox, vault, adapters, and infrastructure services.

Sub-packages:
  adapters/   — Port/adapter implementations (i18n, worker, channel, bus, etc.)
  api/        — HTTP API gateway + middleware
  api_handlers/ — Per-domain API handlers (agent, card, config, monitor, etc.)
  llm/        — LLM engine and provider implementations
  llm_worker/ — Standalone LLM inference process
  lsp/        — Language server protocol integration
  rpc/        — RPC protocol and transport
  sandbox/    — Policy-driven sandboxed execution
  search/     — Global text search and replace
  sse/        — Server-sent events bridge
  vault/      — Credential vault (encrypted storage)
"""
