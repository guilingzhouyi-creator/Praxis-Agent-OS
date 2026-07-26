# Praxis Agent OS — Reference

> **Audience:** Developers, operators. Reference material, not narrative.  
> **Corresponds to:** actual code tree under `src/`.

## File Layout (complete)

```
praxis/
├── pyproject.toml
├── praxis.yaml
├── .nomos-rules.md
├── commands.yaml                    # 39 command definitions
├── tools.yaml                       # Tool metadata
├── .gitignore
│
├── src/
│   ├── l1/kernel/                   # === L1: KERNEL ===
│   │   ├── __init__.py              # Syscall dispatcher (261 lines)
│   │   ├── os.py                    # OS lifecycle (211 lines)
│   │   ├── sync.py                  # Mutex/Semaphore/Barrier/RWLock (350 lines)
│   │   ├── process.py               # ProcessTable + PCB (274 lines)
│   │   ├── allocator.py             # Token allocator + GC (232 lines)
│   │   ├── event.py                 # EventBus pub/sub (133 lines)
│   │   ├── gatechain.py             # G1-G5 authorization (278 lines)
│   │   ├── constitution.py          # Rules engine (392 lines)
│   │   ├── vfs.py                   # Virtual file system (269 lines)
│   │   ├── ipc.py                   # LockChannel + LockBus (106 lines)
│   │   ├── device.py                # Device manager (217 lines)
│   │   ├── persist.py               # SQLite event store (270 lines)
│   │   ├── reputation.py            # Agent trust scores (60 lines)
│   │   ├── tool_chain.py            # Fingerprint chain (262 lines)
│   │   ├── swapper.py               # Ring memory swapper (119 lines)
│   │   ├── settings.py              # Config store proxy (37 lines)
│   │   ├── skill.py                 # Skill manager (227 lines)
│   │   ├── interrupt.py             # Interrupt table (58 lines)
│   │   ├── net.py                   # Network mesh (230 lines)
│   │   ├── net_transport.py         # Transport layer + TLS (239 lines)
│   │   ├── ports.py                 # Port interfaces (247 lines)
│   │   ├── registry.py              # Central system registry (70 lines)
│   │   ├── health.py                # Kernel health check (138 lines)
│   │   ├── resource.py              # Resource limiter (105 lines)
│   │   ├── prompts.py               # Prompt registry (348 lines)
│   │   ├── commands.py              # Command registry (136 lines)
│   │   ├── model_registry.py        # LLM model registry (248 lines)
│   │   ├── platform.py              # Cross-platform detection (172 lines)
│   │   ├── errors.py                # 20 error codes (167 lines)
│   │   ├── rule_descriptor.py       # Rule definition (84 lines)
│   │   └── versioning.py            # Schema migration (81 lines)
│   │
│   │   └── params/                  # === CONSTANTS ===
│   │       ├── __init__.py          # Docstring only — no re-exports
│   │       ├── kernel.py            # 129 constants: allocator, sync, gatechain, process
│   │       ├── agent.py             # 153 constants: roles, terminal, loop, card, events
│   │       ├── tool.py              # 33 constants: danger, timeouts, HTN
│   │       ├── api.py               # 111 constants: API, LLM, network, IPC, env vars
│   │       └── system.py            # 163 constants: cache, memory rings, data paths
│   │
│   ├── l2/                          # === L2: SHELL ===
│   │   ├── l2_shell/
│   │   │   ├── __init__.py          # dispatch() (87 lines)
│   │   │   ├── commands.py          # 39 command handlers (764 lines)
│   │   │   ├── completer.py         # Auto-complete (67 lines)
│   │   │   ├── output_guard.py      # Output filtering (15 lines)
│   │   │   └── state.py             # ShellState (27 lines)
│   │   ├── i18n.py                  # Internationalization (62 lines)
│   │   ├── selector.py              # Agent pre-select (199 lines)
│   │   ├── shell.py                 # Shell entry (199 lines)
│   │   ├── shell_session.py         # Session lifecycle (129 lines)
│   │   └── shell_completer.py       # Completion engine (34 lines)
│   │
│   ├── l3/                          # === L3: CELL ===
│   │   ├── cell/__init__.py         # Cell class, 28 methods (1028 lines)
│   │   ├── agent_terminal/__init__.py # AgentTerminal, 20+ methods (621 lines)
│   │   ├── error_bus/
│   │   │   ├── __init__.py          # ErrorBus, error_boundary, capture (725 lines)
│   │   │   └── api.py               # 6 API handlers (74 lines)
│   │   ├── resource_buffer/
│   │   │   ├── __init__.py
│   │   │   ├── ring.py              # RingBuffer
│   │   │   ├── manager.py           # ResourceBufferManager (62 lines)
│   │   │   └── api.py               # Buffer API handlers
│   │   ├── tools/                   # 35+ tool implementations
│   │   │   ├── _files.py            # File operations (via buffer)
│   │   │   ├── _code.py             # Code analysis
│   │   │   ├── _search.py           # Search tools
│   │   │   ├── _build.py            # Build tools
│   │   │   ├── _git.py              # Git tools
│   │   │   ├── _comm.py             # Communication
│   │   │   ├── _config.py           # Config tools
│   │   │   ├── _env.py              # Environment tools
│   │   │   ├── _archive.py          # Archive tools
│   │   │   ├── _memory.py           # Memory tools
│   │   │   ├── _peer.py             # Peer tools
│   │   │   ├── _terminal.py         # Terminal tools
│   │   │   ├── _web.py              # Web tools
│   │   │   ├── _logging.py          # Logging tools
│   │   │   └── _deps.py             # Dependency tools
│   │   │
│   │   ├── boot.py                  # System bootstrap (529 lines)
│   │   ├── boot_init.py             # Memory/shutdown init (90 lines)
│   │   ├── bootstrap.py             # YAML bootstrap wizard (277 lines)
│   │   ├── agent_loop.py            # LLM tool-calling loop (375 lines)
│   │   ├── memory.py                # MemoryManager — 3-ring (469 lines)
│   │   ├── memory_init.py           # Memory lifecycle (265 lines)
│   │   ├── memory_ring.py           # RingLayer, MemEntry (125 lines)
│   │   ├── memory_quality.py        # Quality scoring (75 lines)
│   │   ├── central_memory.py        # R1-R4 coordinator (139 lines)
│   │   ├── card.py                  # Card data model (82 lines)
│   │   ├── card_unified.py          # Unified card types (466 lines)
│   │   ├── card_registry.py         # Card queue + status (423 lines)
│   │   ├── card_builder.py          # Intent→Card compiler (179 lines)
│   │   ├── card_gate.py             # Card approval gate (197 lines)
│   │   ├── card_state.py            # Backward-compat re-exports (9 lines)
│   │   ├── card_yaml.py             # YAML card loader (48 lines)
│   │   ├── card_pool.py             # Remote card registry (154 lines)
│   │   ├── card_registry_protocol.py # Net protocol (68 lines)
│   │   ├── scout.py                 # Scout pool (310 lines)
│   │   ├── context.py               # Context register (145 lines)
│   │   ├── context_pool.py          # Per-agent context pool (76 lines)
│   │   ├── cell_token_merger.py     # Token accumulator (55 lines)
│   │   ├── monitor_bus.py           # Monitoring event bus (179 lines)
│   │   ├── message_gate.py          # Message policy engine (134 lines)
│   │   ├── tool_spec.py             # ToolSpec registry (449 lines)
│   │   ├── tool_pipeline.py         # 9-step execution (251 lines)
│   │   ├── tool_config.py           # YAML tool config (201 lines)
│   │   ├── tool_policy.py           # Tool visibility policy (198 lines)
│   │   ├── tool_mode.py             # Global read/write mode (78 lines)
│   │   ├── htn_planner.py           # HTN planner (386 lines)
│   │   ├── execution_plan.py        # Card→Plan compiler (537 lines)
│   │   ├── execution_engine.py      # Step execution (316 lines)
│   │   ├── execution_verify.py      # Verification chain (78 lines)
│   │   ├── l3.py                    # L3 coordinator (183 lines)
│   │   ├── l3a.py                   # L3A: Human→Card (175 lines)
│   │   ├── l3b.py                   # L3B: Cross-cell (66 lines)
│   │   ├── central_security.py      # 6-gate check (135 lines)
│   │   ├── central_plugin.py        # Plugin lifecycle (125 lines)
│   │   ├── central_collector.py     # Token aggregation (123 lines)
│   │   ├── scheduler.py             # Unified scheduler (146 lines)
│   │   ├── scheduler_rate.py        # Rate scheduler (54 lines)
│   │   ├── scheduler_scope.py       # Scope scheduling (53 lines)
│   │   ├── scheduler_time.py        # Time-slice (106 lines)
│   │   ├── scheduler_router.py      # Intent routing (99 lines)
│   │   ├── scheduler_types.py       # Dataclasses (46 lines)
│   │   ├── convention.py            # Convention meetings (241 lines)
│   │   ├── convergence.py           # Convergence detection (127 lines)
│   │   ├── fault_tolerance.py       # Checkpoint + recovery (275 lines)
│   │   ├── dialogue_session.py      # Dialogue persistence (284 lines)
│   │   ├── session_export.py        # Session export (285 lines)
│   │   ├── session_snapshot.py      # Snapshot lifecycle (52 lines)
│   │   ├── approval_gate.py         # Human approval (130 lines)
│   │   ├── pending_queue.py         # Approval queue (230 lines)
│   │   ├── reference_channel.py     # Event capture (222 lines)
│   │   ├── log.py                   # Log service + rotation (236 lines)
│   │   ├── config_loader.py         # praxis.yaml loader (234 lines)
│   │   ├── config_handlers.py       # Config migration (252 lines)
│   │   ├── settings_center.py       # 3-layer settings (200 lines)
│   │   ├── settings_adapter.py      # Settings adapter (45 lines)
│   │   ├── identity.py              # Ed25519 keys + proofs (323 lines)
│   │   ├── wiring.py                # Port→adapter wiring (167 lines)
│   │   ├── service_manager.py       # Service lifecycle (187 lines)
│   │   ├── acb.py                   # Agent Control Block (267 lines)
│   │   ├── r4_agent.py              # R4 archivist (383 lines)
│   │   ├── subagent.py              # Lightweight sub-agent (111 lines)
│   │   ├── subagent_framework.py    # Subagent framework (396 lines)
│   │   ├── pager.py                 # Context paging (263 lines)
│   │   ├── pager_bridge.py          # Swapper↔Pager bridge (80 lines)
│   │   ├── pal_router.py            # LLM cost router (144 lines)
│   │   ├── stagnation.py            # Deadlock detection (160 lines)
│   │   ├── loop_detectors.py        # Loop detection (67 lines)
│   │   ├── counter.py               # Token/tool/turn counters (282 lines)
│   │   ├── cache.py                 # Multi-level cache (252 lines)
│   │   ├── cache_doc.py             # Meeting doc cache (122 lines)
│   │   ├── cache_strategy.py        # LLM prefix cache (82 lines)
│   │   ├── result_store.py          # Tool result cache (136 lines)
│   │   ├── sequence_monitor.py      # Anomaly detection (224 lines)
│   │   ├── file_editor.py           # Semantic file editing (547 lines)
│   │   ├── archive_orchestrator.py  # Archive (85 lines)
│   │   ├── process.py               # Process manager (114 lines)
│   │   ├── task_bus.py              # Task dispatch (189 lines)
│   │   ├── todo.py                  # Task queue (176 lines)
│   │   ├── todo_tracker.py          # Todo state machine (218 lines)
│   │   ├── issue.py                 # Issue tracking (244 lines)
│   │   ├── transaction_area.py      # Card staging (269 lines)
│   │   ├── verifier.py              # Result verification (99 lines)
│   │   ├── verify_cadence.py        # Check cadence (80 lines)
│   │   ├── review.py                # Peer review (104 lines)
│   │   ├── vspace.py                # Virtual space (252 lines)
│   │   ├── workspace.py             # Workspace manager (66 lines)
│   │   ├── statecharts.py           # 5-region state machine (266 lines)
│   │   ├── observability_bus.py     # Alert/health/metric (112 lines)
│   │   ├── assembly.py              # Constitutional assembly (176 lines)
│   │   ├── prompt_engine.py         # Prompt building (384 lines)
│   │   ├── template.py              # Jinja2 templates (67 lines)
│   │   ├── content_trust.py         # Content provenance (297 lines)
│   │   ├── comm_monitor.py          # Communication monitor (150 lines)
│   │   ├── ai.py                    # AI service (108 lines)
│   │   ├── config.py                # Config API (89 lines)
│   │   ├── think_registry.py        # Think quota registry (247 lines)
│   │   ├── convergence.py           # Convention→Card (127 lines)
│   │   ├── ipc.py                   # IPC protocol (265 lines)
│   │   ├── plan_step_types.py       # Plan step data (32 lines)
│   │   ├── fs.py                    # Filesystem ops (165 lines)
│   │   ├── network.py               # HTTP client (195 lines) — unused?
│   │   ├── git.py                   # Git ops (122 lines) — unused?
│   │   └── ... (_base, _pool, _term*, _persistable)
│   │
│   ├── l4/                          # === L4: BRIDGE ===
│   │   ├── api_gateway.py           # HTTP server (326 lines)
│   │   ├── api_handlers/__init__.py # Handler mixin (587 lines)
│   │   ├── api_routes.py            # 153 routes (197 lines)
│   │   ├── api_handlers_cards.py    # Card handlers (79 lines)
│   │   ├── api_handlers_monitor.py  # Monitor handlers (145 lines)
│   │   ├── api_handlers_agent.py    # Agent handlers (67 lines)
│   │   ├── api_handlers_config.py   # Config handlers (142 lines)
│   │   ├── api_middleware.py        # Middleware chain (233 lines)
│   │   ├── llm.py                   # LLM Engine (458 lines)
│   │   ├── llm_base.py              # LLMProvider ABC (147 lines)
│   │   ├── llm_providers.py         # Provider impls (265 lines)
│   │   ├── llm_worker/              # Worker process (88 lines)
│   │   ├── mcp_bridge.py            # MCP adapter (500 lines)
│   │   ├── lsp_manager.py           # LSP manager (507 lines)
│   │   ├── lsp.py                   # LSP client (230 lines)
│   │   ├── sandbox.py               # Sandbox interface (282 lines)
│   │   ├── sandbox/                 # Sandbox mgr + server (219 lines)
│   │   ├── rpc/                     # RPC protocol + transport (63 lines)
│   │   ├── supervisor.py            # Process supervisor (188 lines)
│   │   ├── cron_scheduler.py        # Cron scheduling (193 lines)
│   │   ├── credential_vault.py      # AES-256 vault (171 lines)
│   │   ├── search_engine.py         # Full-text search (469 lines)
│   │   ├── sse_bridge.py            # SSE streaming (106 lines)
│   │   ├── auth.py                  # Authentication (115 lines)
│   │   ├── user_session.py          # User sessions (124 lines)
│   │   ├── notify.py                # Webhooks (76 lines)
│   │   ├── net_client.py            # HTTP client (73 lines)
│   │   ├── ops_console.py           # Dashboard (242 lines)
│   │   ├── search.py                # Text search (104 lines)
│   │   ├── ci.py                    # CI pipeline (197 lines)
│   │   ├── git.py                   # Git ops (122 lines)
│   │   └── adapters/
│   │       ├── bus_memory.py        # MemoryBusAdapter (76 lines)
│   │       ├── card_registry.py     # CardRegistryAdapter (30 lines)
│   │       ├── channel_ring.py      # RingChannel (120 lines)
│   │       ├── i18n_yaml.py         # YamlI18nAdapter (117 lines)
│   │       ├── monitor_bus.py       # MonitorBusAdapter (38 lines)
│   │       └── worker_thread.py     # ThreadPoolWorker (170 lines)
│   │
│   ├── l5/                          # === L5: USER ===
│   │   ├── cli.py                   # CLI entry (259 lines)
│   │   └── agent_runtime.py         # Runtime loop (142 lines)
│   │
│   └── services/                    # Empty — files migrated to l2/l3/l4
│
├── tests/
│   ├── test_layer_imports.py        # Layer constraint enforcement
│   ├── test_params_integrity.py     # 17 tests — constant integrity
│   ├── test_kernel.py               # 26 tests — kernel modules
│   ├── test_services_core.py        # 21 tests — services
│   ├── test_api_routes.py           # 19 tests — route matching
│   └── ...
│
└── docs/
    ├── architecture/
    │   ├── overview.md              # This directory root
    │   ├── reference.md             # This file
    │   └── deep-dive/               # Detailed subsystem docs
    │       ├── boot-sequence.md
    │       ├── gatechain.md
    │       ├── memory.md
    │       ├── tool-pipeline.md
    │       ├── cell-agent.md
    │       ├── card-lifecycle.md
    │       └── security.md
    └── design/
        └── praxis-architecture-actual.md  # Legacy (to archive)
```

## Constants Reference

### `params/kernel.py` (129 constants)

| Section | Key Constants |
|---------|--------------|
| Allocator | `ALLOCATOR_DEFAULTS.{tokens=4096, ring1=32, ring2=200, ring3=1000}` |
| Mutex | `MUTEX_DEFAULT_TIMEOUT=30.0`, `MUTEX_DEFAULT_PRIORITY=5.0` |
| Semaphore | `SEMAPHORE_DEFAULT_MAX=3`, `SEMAPHORE_DEFAULT_TIMEOUT=30.0` |
| Barrier | `BARRIER_DEFAULT_COUNT=3`, `BARRIER_DEFAULT_TIMEOUT=60.0` |
| RWLock | `RWLOCK_DEFAULT_TIMEOUT=30.0` |
| Event | `EVENT_QUERY_LIMIT=20` |
| Process | `PROCESS_AUDIT_MAX=1000`, `PROCESS_INIT_RING=3` |
| ToolChain | `TOOLCHAIN_MAX_CALLS=5000` |
| GateChain | `GATECHAIN_RISK_WARN_THRESHOLD=6.0`, `GATECHAIN_REPEAT_THRESHOLD=5` |
| VFS | `VFS_DEFAULT_MIN_RING=1` |
| Syscall | `SYSCALL_AUDIT_MAX=5000` |
| Stagnation | `STAGNATION_SPIN_THRESHOLD=3` |
| Ring | `RING_1`, `RING_2_5`, `RING_3` + `RING_NUM_MAP` + `RING_NAME_MAP` |
| GateStatus | `PASS`, `WARN`, `BLOCK`, `REPORT` |
| WitnessStatus | `PENDING`, `APPROVED`, `REJECTED` |

### `params/agent.py` (153 constants)

| Section | Key Constants |
|---------|--------------|
| Constitution | `BUILTIN_RULE_DEFS` (15 rules), `CONSTITUTION_FILE_ACTIONS`, `CONSTITUTION_MODIFY_ACTIONS` |
| Agent | `AgentDefaults`, `DEFAULT_AGENT_CONFIGS`, `CENTRAL_ROLES`, `AGENT_CLEARANCE` |
| Terminal | `TERMINAL_MODE_VALID=("assembly","direct")`, `CACHE_KEEPALIVE_INTERVAL=240.0` |
| Loop | `AGENT_LOOP_DEFAULT_STEPS=10`, `AGENT_LOOP_DEFAULT_TIMEOUT=120.0` |
| Scout | `SCOUT_LOOP_STEPS=10`, `SCOUT_LOOP_TIMEOUT=180.0` |
| Events | `EVENT_TASK_ASSIGN`, `EVENT_REVIEW_REQUESTED`, `EVENT_TOKEN_USAGE`, `EVENT_CROSS_REVIEW`, `EVENT_AGENT_BOOT`, `EVENT_ARCHIVE_ALERT` |
| Card | `CARD_GATE_APPROVAL_TIMEOUT=3600.0`, `CARD_BUILDER_MODES` |
| Cell | `CELL_ROLLBACK_RING_SIZE=20`, `CELL_MAILBOX_MAX_PER_AGENT=100` |
| Agent Status | `AGENT_STATUS_IDLE`, `AGENT_STATUS_PROCESSING`, `AGENT_STATUS_CRASHED`, `AGENT_STATUS_BOOTING` |

### `params/tool.py` (33 constants)

| Section | Key Constants |
|---------|--------------|
| Danger | `TOOL_DANGER_LEVEL` {0-3}, `DANGER_TO_GATES` |
| Timeouts | `TOOL_BUILD_TIMEOUT=300`, `TOOL_PIP_TIMEOUT=120`, `TOOL_GIT_TIMEOUT=30`, `TOOL_TERMINAL_TIMEOUT=30.0` |
| Rates | `TOOL_RATE_RING_1=60/min`, `TOOL_RATE_RING_2_5=20/min`, `TOOL_RATE_RING_3=5/min` |
| HTN | `HTN_DEFAULT_TOOLS` (14 tool mappings) |

### `params/api.py` (111 constants)

| Section | Key Constants |
|---------|--------------|
| PAL | `PAL_FRUGAL_COST=1`, `PAL_STANDARD_COST=10`, `PAL_FRONTIER_COST=30` |
| LLM | `LLM_RATE_LIMIT_WAIT=60`, `LLM_PROVIDER_URLS` (openai/anthropic/ollama) |
| API | `API_GATEWAY_PORT=8080`, `API_GATEWAY_HOST="127.0.0.1"`, API_CORS_* |
| Network | `BROADCAST_INTERVAL=15.0`, `PEER_TIMEOUT=60.0`, `DISCOVERY_PORT_DEFAULT=42069` |
| IPC | `IPC_SOCKET_DIR`, `IPC_KERNEL_SOCKET`, `IPC_LLM_SOCKET` |
| Env Vars | `ENV_OPENAI_KEY`, `ENV_ANTHROPIC_KEY`, `ENV_SANDBOX_ROOT`, 16 total |
| Channel | `CHANNEL_RING_CAPACITY=1024` |
| Worker | `WORKER_POOL_MIN=4`, `WORKER_POOL_MAX=32` |

### `params/system.py` (163 constants)

| Section | Key Constants |
|---------|--------------|
| Cache | `FILE_CACHE_MAX_ENTRIES=500`, `FILE_CACHE_TTL=60.0` |
| Scout Pool | `SCOUT_POOL_MAX_TOTAL=16`, `SCOUT_IDLE_TIMEOUT=60.0` |
| Persistence | `PERSIST_INTERVAL=30.0`, `CARD_REGISTRY_AUTO_SAVE=30.0` |
| Memory Ring | `RING1_CAPACITY=32`, `RING2_CAPACITY=200`, `RING3_CAPACITY=1000` |
| Memory Budget | `MEMORY_RING_WORKING_BUDGET=8192`, `SHORT=32768`, `LONG=131072` |
| Polling | `POLL_INTERVAL_FAST=0.01`, `SLOW=0.05`, `PAUSED=0.5` |
| Sandbox | `SANDBOX_PROFILE_READ_ONLY="DANGER_0"`, `SANDBOX_EXEC_TIMEOUT=300.0` |
| Data Paths | `PRAXIS_DATA_DIR`, `PRAXIS_EVENTS_DB`, `PRAXIS_CARD_REGISTRY`, 25+ paths |
| Token | `TOKEN_CELL_QUOTA=5_000_000`, `TOKEN_GLOBAL_QUOTA=50_000_000` |
| Error Bus | `ERROR_BUS_BUFFER=5000`, `ERROR_BUS_DEDUP_WINDOW=300` |
| Log | `LOG_MAX_MEMORY_ENTRIES=5000`, `LOG_EXPORT_LIMIT=10000` |
| Version | `KERNEL_VERSION="0.3.0"`, `PRAXIS_CODENAME="Aether"` |

## API Routes (153 total)

| Category | Routes | Handler Prefix |
|----------|--------|---------------|
| Core | 8 | `health`, `processes`, `devices`, `settings`, `syscalls`, `peers`, `list_endpoints`, `endpoints` |
| Cards | 10 | `list_cards`, `get_card`, `submit_card`, `submit_batch`, `card_rollback`, `card_approval_trail`, `card_unified_submit`, `card_plan`, `sideload_dispatch`, `card_gate_history` |
| Card Gate | 4 | `card_gate_stats`, `card_gate_config`, `card_gate_config_set`, `card_types_list` |
| Card Types | 2 | `card_types_list`, `card_types_register` |
| Approvals | 4 | `list_approvals`, `approval_respond`, `gate_pending`, `gate_respond` |
| Pending | 6 | `pending_list`, `pending_approve`, `pending_reject`, `pending_escalate`, `pending_priority`, `pending_stats` |
| Cell | 2 | `cell_stop`, `cell_liveness` |
| Agent | 8 | `agent_list`, `agent_select`, `agent_select_by`, `agent_preconnect`, `agent_reachable`, `agent_direct`, `agent_direct_close`, `agent_review_message` |
| Settings | 2 | `settings`, `set_settings` |
| Security | 4 | `security_check`, `security_stats`, `trust_check`, `trust_stats` |
| Memory | 3 | `memory_store`, `memory_recall`, `memory_stats` |
| Shell | 3 | `shell_dispatch`, `shell_autocomplete`, `shell_commands` |
| MCP | 3 | `mcp_import`, `mcp_list`, `mcp_remove` |
| Plugins | 5 | `plugin_list`, `plugin_install_tool`, `plugin_remove`, `plugin_install_mcp`, `plugin_stats` |
| Tools | 4 | `tool_stats`, `tool_policy_set`, `tool_policy_list`, `tool_policy_remove` |
| Tokens | 3 | `token_stats`, `token_cells`, `token_global` |
| Comm | 2 | `comm_stats`, `comm_recent` |
| Cron | 3 | `cron_list`, `cron_add`, `cron_remove` |
| Credentials | 3 | `credential_status`, `credential_set`, `credential_delete` |
| Bootstrap | 3 | `bootstrap_status`, `bootstrap_defaults`, `bootstrap_apply` |
| Export | 2 | `export_counter`, `export_metrics` |
| Rollback | 1 | `rollback_context` |
| Session | 1 | `session_state` |
| Errors | 6 | `handle_log_errors`, `handle_log_errors_detail`, `handle_log_errors_stats`, `handle_log_errors_trend`, `handle_log_errors_clear`, `handle_log_errors_export` |
| Logs | 4 | `query`, `recent`, `stats`, `export` |
| Config | 4 | `list`, `get`, `set`, `categories` |
| FS | 10 | `edit`, `batch_edit`, `history`, `undo`, `redo`, `patch`, `patch/apply`, `patch/revert`, `patches`, `patch/get` |
| Prompts | 4 | `build`, `context`, `templates`, `template` |
| LSP | 6 | `diagnostics`, `hover`, `servers`, `start`, `stop`, `feedback` |
| Search | 5 | `search`, `semantic`, `symbol`, `docs`, `docs/index` |
| Session | 6 | `export`, `import`, `snapshots`, `snapshot`, `snapshot/restore`, `snapshot/delete` |
| SSE | 1 | `events` |
| Buffer | 4 | `buffer/status`, `buffer/commit`, `buffer/diff`, `buffer/discard` |
| Monitor | 6 | `monitor/events`, `monitor/stats`, `monitor/stream`, `monitor/gate`, `monitor/gate/<id>` |
| V1 | 2 | `v1/tools`, `v1/locales` |

## Error Codes (20)

| Code | Meaning |
|------|---------|
| `E_INTERNAL` | Internal error |
| `E_TIMEOUT` | Operation timed out |
| `E_INVALID_PARAMS` | Invalid parameters |
| `E_NOT_FOUND` | Resource not found |
| `E_CONSTITUTION_BLOCKED` | Blocked by constitution |
| `E_GATECHAIN_BLOCKED` | Blocked by gate chain |
| `E_TOOL_MUTED` | Tool is muted |
| `E_TOOL_NOT_FOUND` | Tool not found |
| `E_RESOURCE_EXHAUSTED` | Resource exhausted |
| `E_PERMISSION_DENIED` | Permission denied |
| `E_CELL_EMERGENCY` | Cell in emergency stop |
| `E_CHECKPOINT_RESTORE` | Checkpoint restore failed |
| `E_AGENT_CRASHED` | Agent crashed |
| `E_HUMAN_REJECTED` | Rejected by human |
| `E_APPROVAL_TIMEOUT` | Approval timed out |
| `E_MCP_FAILED` | MCP call failed |
| `E_UNKNOWN_TOOL` | Unknown tool |
| `E_HANDLER_ERROR` | Handler error |
| `E_MEMORY_REJECTED` | Memory quality rejected |
| `E_SANDBOX_ERROR` | Sandbox operation failed |

## Port Interfaces (7)

Defined in `l1/kernel/ports.py`:

| Port | Adapter(s) | File |
|------|-----------|------|
| `TransportPort` | `TcpAdapter` | `l4/adapters/channel_ring.py` |
| `ChannelPort` | `RingChannel` | `l4/adapters/channel_ring.py` |
| `EventBusPort` | `MemoryBusAdapter` | `l4/adapters/bus_memory.py` |
| `WorkerPort` | `ThreadPoolWorker` | `l4/adapters/worker_thread.py` |
| `I18nPort` | `YamlI18nAdapter` | `l4/adapters/i18n_yaml.py` |
| `CardRegistryPort` | `CardRegistryAdapter` | `l4/adapters/card_registry.py` |
| `MonitorBusPort` | `MonitorBusAdapter` | `l4/adapters/monitor_bus.py` |

## Layer Import Allowlist (49 entries)

Pre-existing cross-layer imports exempted from the strict one-way rule in `test_layer_imports.py`:

| Pattern | Files | Reason |
|---------|-------|--------|
| L1 → L3/L4 | 5 | Adapter ports (settings → adapter, net → worker/channel) |
| L2 → L3/L4 | 3 | Shell accessing L3 services + i18n adapter |
| L3 → L4 (LLM) | 6 | AgentLoop, cache, card_registry etc. need LLM |
| L3 → L4 (adapters) | 6 | wiring.py boot-time port assembly |
| L3 → L4 (services) | 4 | Config handlers, prompt engine, sandbox, notify |
| L2 → L3 | 2 | Shell think registry + cell access |
| L1 → L4 | 1 | model_registry needs LLM base |

## Environment Variables (16)

Defined in `params/api.py`:

| Variable | Constant | Used By |
|----------|----------|---------|
| `OPENAI_API_KEY` | `ENV_OPENAI_KEY` | `l4/llm_providers.py` |
| `DEEPSEEK_API_KEY` | `ENV_DEEPSEEK_KEY` | `l4/llm_providers.py` |
| `ANTHROPIC_API_KEY` | `ENV_ANTHROPIC_KEY` | `l4/llm_providers.py` |
| `OLLAMA_URL` | `ENV_OLLAMA_URL` | `l4/llm_providers.py` |
| `OLLAMA_MODEL` | `ENV_OLLAMA_MODEL` | `l4/llm_providers.py` |
| `OPENAI_API_URL` | `ENV_OPENAI_URL` | `l4/llm_providers.py` |
| `OPENAI_MODEL` | `ENV_OPENAI_MODEL` | `l4/llm_providers.py` |
| `ANTHROPIC_API_URL` | `ENV_ANTHROPIC_URL` | `l4/llm_providers.py` |
| `ANTHROPIC_MODEL` | `ENV_ANTHROPIC_MODEL` | `l4/llm_providers.py` |
| `LLM_WS_URL` | `ENV_LLM_WS_URL` | `l4/llm_providers.py` |
| `LLM_WS_MODEL` | `ENV_LLM_WS_MODEL` | `l4/llm_providers.py` |
| `NOMOS_SANDBOX_ROOT` | `ENV_SANDBOX_ROOT` | `l4/sandbox.py`, `l3/vspace.py` |
| `PRAXIS_DISCOVERY_PORT` | `ENV_DISCOVERY_PORT` | `l3/config_handlers.py` |
| `PRAXIS_PORT` | `ENV_PRAXIS_PORT` | `l3/config_handlers.py` |
| `NOMOS_DEFAULT_CELL` | `ENV_DEFAULT_CELL` | — |
| `PRAXIS_API_TOKEN` | `ENV_API_TOKEN` | — |

## State File Paths (25+)

All under `PRAXIS_DATA_DIR` (default: `$TMPDIR/nomos-praxis-data/`):

| Constant | File |
|----------|------|
| `PRAXIS_EVENTS_DB` | `events.db` |
| `PRAXIS_STATE_JSON` | `state.json` |
| `PRAXIS_CARD_REGISTRY` | `card_registry.json` |
| `PRAXIS_CARD_GATE` | `card_gate.json` |
| `PRAXIS_PENDING_QUEUE` | `pending_queue.json` |
| `PRAXIS_APPROVAL_GATE` | `approval_gate.json` |
| `PRAXIS_SANDBOX_STATE` | `sandbox_state.json` |
| `PRAXIS_TODO_TABLE` | `todo_table.json` |
| `PRAXIS_EXECUTION_RESULTS` | `execution_results.json` |
| `PRAXIS_DIALOGUE_SESSION` | `dialogue_session.json` |
| `PRAXIS_ARCHIVE_DB` | `archive.db` |
| `PRAXIS_MCP_STATE` | `mcp_state.json` |
| `PRAXIS_MESSAGE_GATE_STATE` | `message_gate.json` |
| `PRAXIS_MONITOR_BUS_LOG` | `monitor_bus.jsonl` |
| `PRAXIS_VAULT_SALT` | `.praxis_vault_salt` |
| `PRAXIS_SETTINGS_FILE` | `.praxis_settings.json` (in CWD) |

Plus template paths: `cell_{}.json`, `seq_monitor_{}.json`, `{}.state.json`, `{}.snapshot.json`.
