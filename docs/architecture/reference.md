# Praxis Agent OS — Reference

> **Audience:** Developers, operators. Reference material, not narrative.  
> **Corresponds to:** actual code tree under `src/`.

## File Layout (complete)

```
praxis/
├── pyproject.toml
├── praxis.yaml
├── .nomos-rules.md
├── commands.yaml                    # 40 command definitions
├── tools.yaml                       # Tool metadata
├── .gitignore
│
├── src/
│   ├── l1/kernel/                   # === L1: KERNEL ===
│   │   ├── __init__.py              # Syscall dispatcher (316 lines)
│   │   ├── os.py                    # OS lifecycle (259 lines)
│   │   ├── sync.py                  # Mutex/Semaphore/Barrier/RWLock (421 lines)
│   │   ├── process.py               # ProcessTable + PCB (325 lines)
│   │   ├── allocator.py             # Token allocator + GC (269 lines)
│   │   ├── event.py                 # EventBus pub/sub (161 lines)
│   │   ├── gatechain.py             # G1-G5 authorization (327 lines)
│   │   ├── constitution.py          # Rules engine (465 lines)
│   │   ├── vfs.py                   # Virtual file system (313 lines)
│   │   ├── ipc.py                   # LockChannel + LockBus (137 lines)
│   │   ├── device.py                # Device manager (259 lines)
│   │   ├── persist.py               # SQLite event store (319 lines)
│   │   ├── reputation.py            # Agent trust scores (82 lines)
│   │   ├── tool_chain.py            # Fingerprint chain (303 lines)
│   │   ├── swapper.py               # Ring memory swapper (142 lines)
│   │   ├── settings.py              # Config store proxy (46 lines)
│   │   ├── skill.py                 # Skill manager (258 lines)
│   │   ├── interrupt.py             # Interrupt table (80 lines)
│   │   ├── net.py                   # Network mesh (282 lines)
│   │   ├── net_transport.py         # Transport layer + TLS (282 lines)
│   │   ├── ports.py                 # Port interfaces (335 lines)
│   │   ├── registry.py              # Central system registry (90 lines)
│   │   ├── health.py                # Kernel health check (162 lines)
│   │   ├── resource.py              # Resource limiter (136 lines)
│   │   ├── prompts.py               # Prompt registry (368 lines)
│   │   ├── commands.py              # CommandRegistry — sys/user cmds, YAML+API metadata (294 lines)
│   │   ├── model_registry.py        # LLM model registry (298 lines)
│   │   ├── platform.py              # Cross-platform detection (217 lines)
│   │   ├── errors.py                # 20 error codes (208 lines)
│   │   ├── rule_descriptor.py       # Rule definition (106 lines)
│   │   ├── bus.py                   # SystemBus — component lifecycle, topology, health (421 lines)
│   │   └── versioning.py            # Schema migration (107 lines)
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
│   │   │   ├── __init__.py          # dispatch() (105 lines)
│   │   │   ├── commands.py          # 39 command handlers (870 lines)
│   │   │   ├── completer.py         # Auto-complete (84 lines)
│   │   │   ├── output_guard.py      # Output filtering (22 lines)
│   │   │   └── state.py             # ShellState (39 lines)
│   │   ├── i18n.py                  # Internationalization (90 lines)
│   │   ├── selector.py              # Agent pre-select (253 lines)
│   │   ├── shell.py                 # Shell entry (228 lines)
│   │   ├── shell_session.py         # Session lifecycle (155 lines)
│   │   └── shell_completer.py       # Completion engine (44 lines)
│   │
│   ├── l3/                          # === L3: CELL ===
│   │   ├── __init__.py              # Root init
│   │   ├── _base.py                 # Base classes (93 lines)
│   │   ├── _persistable.py          # Persistable mixin (104 lines)
│   │   ├── _pool.py                 # Pool utilities (191 lines)
│   │   │
│   │   ├── agent/                   # AgentLoop, Scout, SubAgent (22 files)
│   │   │   ├── __init__.py
│   │   │   ├── agent_loop.py        # LLM tool-calling loop (421 lines)
│   │   │   ├── agent_persist.py     # Agent persistence
│   │   │   ├── ai.py                # AI service (127 lines)
│   │   │   ├── convergence.py       # Convention→Card / convergence detection (156 lines)
│   │   │   ├── pal_router.py        # LLM cost router (178 lines)
│   │   │   ├── review.py            # Peer review (127 lines)
│   │   │   ├── scout.py             # Scout pool (373 lines)
│   │   │   ├── session_snapshot.py  # Snapshot lifecycle (69 lines)
│   │   │   ├── stagnation.py        # Deadlock detection (195 lines)
│   │   │   ├── subagent.py          # Lightweight sub-agent (111 lines)
│   │   │   ├── subagent_dispatcher.py # @mention parsing (92 lines)
│   │   │   ├── subagent_framework.py # Facade over spec/task/dispatch/merge (115 lines)
│   │   │   ├── subagent_merger.py   # ResultMerger (58 lines)
│   │   │   ├── subagent_spec.py     # SubAgentSpec dataclass (142 lines)
│   │   │   ├── subagent_task.py     # SubAgentTask (AgentLoop execution) (223 lines)
│   │   │   ├── verifier.py          # Result verification (120 lines)
│   │   │   ├── verify_cadence.py    # Check cadence (97 lines)
│   │   │   ├── _term_convention.py  # Terminal convention utilities (126 lines)
│   │   │   ├── _term_handlers.py    # Terminal handler logic (339 lines)
│   │   │   ├── _term_lifecycle.py   # Terminal lifecycle (51 lines)
│   │   │   └── _term_types.py       # Terminal types (44 lines)
│   │   │
│   │   ├── agent_terminal/          # Terminal runtime
│   │   │   └── __init__.py          # AgentTerminal, 34 methods (639 lines)
│   │   │
│   │   ├── boot/                    # Boot sequence + wiring (4 files)
│   │   │   ├── __init__.py
│   │   │   ├── boot.py              # 5-step system bootstrap (528 lines)
│   │   │   ├── boot_init.py         # Memory/shutdown init (107 lines)
│   │   │   └── wiring.py            # Port→adapter wiring (210 lines)
│   │   │
│   │   ├── bus/                     # IPC, L3B, MonitorBus, HTN (15 files)
│   │   │   ├── __init__.py
│   │   │   ├── comm_monitor.py      # Communication monitor (182 lines)
│   │   │   ├── htn_a.py             # Global intent sharding
│   │   │   ├── htn_b.py             # Inter-cell routing decomposition
│   │   │   ├── htn_planner.py       # HTN planner (452 lines)
│   │   │   ├── ipc.py               # IPC protocol (323 lines)
│   │   │   ├── l3b.py               # L3B: Cross-cell (81 lines)
│   │   │   ├── l3b_bus.py           # Composite communication bus (5 message types)
│   │   │   ├── l3b_message_pool.py  # 2-tier buffer: Hot Ring + SQLite
│   │   │   ├── log.py               # Log service + rotation (288 lines)
│   │   │   ├── message_gate.py      # Message policy engine (169 lines)
│   │   │   ├── monitor_bus.py       # Monitoring event bus (220 lines)
│   │   │   ├── observability_bus.py # Alert/health/metric (143 lines)
│   │   │   ├── reference_channel.py # Event capture (260 lines)
│   │   │   └── task_bus.py          # Task dispatch (220 lines)
│   │   │
│   │   ├── card/                    # Card lifecycle + registry (21 files)
│   │   │   ├── __init__.py
│   │   │   ├── approval_gate.py     # Human approval (155 lines)
│   │   │   ├── card_builder.py      # Intent→Card compiler (227 lines)
│   │   │   ├── card_gate.py         # Card approval gate (252 lines)
│   │   │   ├── card_pool.py         # Remote card registry (183 lines)
│   │   │   ├── card_registry.py     # Card queue + status (490 lines)
│   │   │   ├── card_registry_protocol.py # Net protocol (80 lines)
│   │   │   ├── card_unified.py      # Unified card types (550 lines)
│   │   │   ├── card_yaml.py         # YAML card loader (58 lines)
│   │   │   ├── convention.py        # Convention meetings (280 lines)
│   │   │   ├── decomposer.py        # Intent decomposition (265 lines)
│   │   │   ├── dialogue_session.py  # Dialogue persistence (325 lines)
│   │   │   ├── execution_engine.py  # Step execution (386 lines)
│   │   │   ├── execution_plan.py    # Card→Plan compiler (613 lines)
│   │   │   ├── execution_run.py     # Execution runner
│   │   │   ├── execution_verify.py  # Verification chain (96 lines)
│   │   │   ├── issue.py             # Issue tracking (286 lines)
│   │   │   ├── models.py            # Card model types
│   │   │   ├── pending_queue.py     # Approval queue (270 lines)
│   │   │   ├── plan_step_types.py   # Plan step data (38 lines)
│   │   │   └── transaction_area.py  # Card staging (302 lines)
│   │   │
│   │   ├── cell/                    # Cell class + components + peers (22 files)
│   │   │   ├── __init__.py          # Cell class, 28+ methods (1048 lines)
│   │   │   ├── components/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── cell_agent.py    # Agent registration
│   │   │   │   ├── cell_buffer.py   # CircularBuffer (65 lines)
│   │   │   │   ├── cell_cache.py    # L2 shared cache (383 lines)
│   │   │   │   ├── cell_convention.py # Cell convention helpers (139 lines)
│   │   │   │   ├── cell_cross_review.py # Cross-review
│   │   │   │   ├── cell_decompose.py # Cell decomposition (101 lines)
│   │   │   │   ├── cell_execute.py  # Cell execution
│   │   │   │   ├── cell_icache.py   # ICache, LFU (168 lines)
│   │   │   │   ├── cell_interrupt.py # InterruptController, 4 pri (249 lines)
│   │   │   │   ├── cell_mmu.py      # CellMmu + CellTlb (209 lines)
│   │   │   │   ├── cell_monitor.py  # Cell health events (209 lines)
│   │   │   │   ├── cell_pmu.py      # 28 performance counters (199 lines)
│   │   │   │   ├── cell_rollback.py # Cell rollback
│   │   │   │   ├── cell_token_merger.py # Token tracking (68 lines)
│   │   │   │   ├── cell_types.py    # Cell type definitions (100 lines)
│   │   │   │   └── cell_watchdog.py # Watchdog timer (187 lines)
│   │   │   └── peers/
│   │   │       ├── __init__.py
│   │   │       ├── central_collector.py # Token aggregation (149 lines)
│   │   │       ├── l3.py            # L3 coordinator (224 lines)
│   │   │       └── l3a.py           # L3A: Human→Card (212 lines)
│   │   │
│   │   ├── config/                  # Config loading + settings (8 files)
│   │   │   ├── __init__.py
│   │   │   ├── bootstrap.py         # YAML bootstrap wizard (329 lines)
│   │   │   ├── cache_strategy.py    # LLM prefix cache (107 lines)
│   │   │   ├── config.py            # Config API (111 lines)
│   │   │   ├── config_handlers.py   # Config migration (305 lines)
│   │   │   ├── config_loader.py     # praxis.yaml loader (282 lines)
│   │   │   ├── settings_adapter.py  # Settings adapter (67 lines)
│   │   │   └── settings_center.py   # 3-layer settings (247 lines)
│   │   │
│   │   ├── error_bus/               # Error capture bus (2 files)
│   │   │   ├── __init__.py          # ErrorBus, error_boundary (725 lines)
│   │   │   └── api.py               # 6 API handlers (72 lines)
│   │   │
│   │   ├── memory/                  # 4-ring memory + pager + cache (17 files)
│   │   │   ├── __init__.py
│   │   │   ├── archive_orchestrator.py # Archive (104 lines)
│   │   │   ├── cache.py             # Multi-level cache (301 lines)
│   │   │   ├── cache_doc.py         # Meeting doc cache (151 lines)
│   │   │   ├── central_memory.py    # R1-R4 coordinator (165 lines)
│   │   │   ├── context.py           # Context register (181 lines)
│   │   │   ├── context_pool.py      # Per-agent context pool (76 lines)
│   │   │   ├── memory.py            # MemoryManager — 4-ring (536 lines)
│   │   │   ├── memory_context.py    # Memory context
│   │   │   ├── memory_init.py       # Memory lifecycle (318 lines)
│   │   │   ├── memory_quality.py    # Quality scoring (92 lines)
│   │   │   ├── memory_ring.py       # RingLayer, MemEntry (153 lines)
│   │   │   ├── memory_search.py     # Memory search
│   │   │   ├── pager.py             # Context paging (320 lines)
│   │   │   ├── pager_bridge.py      # Swapper↔Pager bridge (106 lines)
│   │   │   ├── r4_agent.py          # R4 archivist (443 lines)
│   │   │   └── result_store.py      # Tool result cache (163 lines)
│   │   │
│   │   ├── resource_buffer/         # Ring file buffer (4 files)
│   │   │   ├── __init__.py
│   │   │   ├── api.py               # Buffer API handlers (36 lines)
│   │   │   ├── manager.py           # ResourceBufferManager (62 lines)
│   │   │   └── ring.py              # RingBuffer (290 lines)
│   │   │
│   │   ├── scheduler/               # 5-D scheduler + think + ACB (11 files)
│   │   │   ├── __init__.py
│   │   │   ├── acb.py               # Agent Control Block (332 lines)
│   │   │   ├── loop_detectors.py    # Loop detection (84 lines)
│   │   │   ├── scheduler.py         # Unified scheduler (177 lines)
│   │   │   ├── scheduler_rate.py    # Rate scheduler (72 lines)
│   │   │   ├── scheduler_router.py  # Intent routing (118 lines)
│   │   │   ├── scheduler_scope.py   # Scope scheduling (75 lines)
│   │   │   ├── scheduler_time.py    # Time-slice (126 lines)
│   │   │   ├── scheduler_types.py   # Dataclasses (57 lines)
│   │   │   ├── sequence_monitor.py  # Anomaly detection (263 lines)
│   │   │   └── think_registry.py    # Think quota registry (247 lines)
│   │   │
│   │   ├── services/                # Stats, Records, Model, etc. (29 files)
│   │   │   ├── __init__.py
│   │   │   ├── assembly.py          # Constitutional assembly (212 lines)
│   │   │   ├── bus_components.py    # Bus component registration
│   │   │   ├── cell_orchestrate.py  # SubAgentOrchestrator (fork-join) (234 lines)
│   │   │   ├── central_plugin.py    # Plugin lifecycle (152 lines)
│   │   │   ├── central_security.py  # 6-gate check (166 lines)
│   │   │   ├── content_trust.py     # Content provenance (367 lines)
│   │   │   ├── counter.py           # Token/tool/turn counters (321 lines)
│   │   │   ├── fault_tolerance.py   # Checkpoint + recovery (323 lines)
│   │   │   ├── file_editor.py       # Semantic file editing (671 lines)
│   │   │   ├── fs.py                # Filesystem ops (199 lines)
│   │   │   ├── global_components.py # Global component registration
│   │   │   ├── hook.py              # Hook system
│   │   │   ├── identity.py          # Ed25519 keys + proofs (391 lines)
│   │   │   ├── middleware.py        # Service middleware
│   │   │   ├── model_service.py     # ModelService — ModelSpec resolution (542 lines)
│   │   │   ├── package_manager.py   # Unified apt/pip/npm/cargo (175 lines)
│   │   │   ├── process.py           # Process manager (139 lines)
│   │   │   ├── prompt_engine.py     # Prompt building (469 lines)
│   │   │   ├── record_center.py     # Unified record center (358 lines)
│   │   │   ├── service_manager.py   # Service lifecycle (220 lines)
│   │   │   ├── session_export.py    # Session export (340 lines)
│   │   │   ├── statecharts.py       # 5-region state machine (301 lines)
│   │   │   ├── stats_center.py      # Cross-Cell metric aggregation (341 lines)
│   │   │   ├── template.py          # Jinja2 templates (85 lines)
│   │   │   ├── todo.py              # Task queue (202 lines)
│   │   │   ├── todo_tracker.py      # Todo state machine (240 lines)
│   │   │   ├── vspace.py            # Virtual space (311 lines)
│   │   │   └── workspace.py         # Workspace manager (86 lines)
│   │   │
│   │   ├── tool_system/             # Tool pipeline + spec + policy (8 files)
│   │   │   ├── __init__.py
│   │   │   ├── tool_config.py       # YAML tool config (250 lines)
│   │   │   ├── tool_mode.py         # Global read/write mode (101 lines)
│   │   │   ├── tool_params.py       # Tool parameter definitions
│   │   │   ├── tool_pipeline.py     # 9-step execution (295 lines)
│   │   │   ├── tool_policy.py       # Tool visibility policy (241 lines)
│   │   │   ├── tool_registry.py     # Tool registry
│   │   │   └── tool_spec.py         # ToolSpec registry (546 lines)
│   │   │
│   │   ├── tools/                   # 17 tool implementations
│   │   │   ├── _archive.py          # Archive tools (74 lines)
│   │   │   ├── _build.py            # Build tools (31 lines)
│   │   │   ├── _code.py             # Code analysis (64 lines)
│   │   │   ├── _comm.py             # Communication (34 lines)
│   │   │   ├── _config.py           # Config tools (44 lines)
│   │   │   ├── _deps.py             # Dependency tools (20 lines)
│   │   │   ├── _env.py              # Environment tools (16 lines)
│   │   │   ├── _files.py            # File operations (131 lines)
│   │   │   ├── _git.py              # Git tools (39 lines)
│   │   │   ├── _logging.py          # Logging tools (21 lines)
│   │   │   ├── _memory.py           # Memory tools (50 lines)
│   │   │   ├── _peer.py             # Peer tools (55 lines)
│   │   │   ├── _search.py           # Search tools (42 lines)
│   │   │   ├── _skills.py           # Skill tools
│   │   │   ├── _subagent.py         # SubAgent tools
│   │   │   ├── _terminal.py         # Terminal tools (17 lines)
│   │   │   └── _web.py              # Web tools (40 lines)
│   │
│   ├── l4/                          # === L4: BRIDGE ===
│   │   ├── api/                     # HTTP gateway + routes + middleware
│   │   │   ├── __init__.py
│   │   │   ├── api_gateway.py       # HTTP server (393 lines)
│   │   │   ├── api_routes.py        # 157 routes (234 lines)
│   │   │   ├── api_middleware.py    # Middleware chain (312 lines)
│   │   │   └── api_handlers_cards.py # Card handlers (93 lines)
│   │   │
│   │   ├── api_handlers/            # 9 handler modules
│   │   │   ├── __init__.py          # Handler mixin (688 lines)
│   │   │   ├── api_handlers_agent.py # Agent handlers (83 lines)
│   │   │   ├── api_handlers_cluster.py # Cluster handlers
│   │   │   ├── api_handlers_commands.py # Command handlers
│   │   │   ├── api_handlers_config.py # Config handlers (168 lines)
│   │   │   ├── api_handlers_monitor.py # Monitor handlers (188 lines)
│   │   │   ├── api_handlers_providers.py # Provider + model-spec API (18 routes)
│   │   │   ├── api_handlers_records.py # RecordCenter query/stats/export (91 lines)
│   │   │   └── api_handlers_stats.py # StatsCenter query/top/live (101 lines)
│   │   │
│   │   ├── llm/                     # LLM engine + providers
│   │   │   ├── __init__.py
│   │   │   ├── llm.py               # LLM Engine (542 lines)
│   │   │   ├── llm_base.py          # LLMProvider ABC (186 lines)
│   │   │   └── llm_providers.py     # Provider impls (299 lines)
│   │   │
│   │   ├── search/                  # Search engine
│   │   │   ├── __init__.py
│   │   │   ├── search.py            # Text search (124 lines)
│   │   │   └── search_engine.py     # Full-text search (556 lines)
│   │   │
│   │   ├── lsp/                     # LSP client + manager
│   │   │   ├── __init__.py
│   │   │   ├── lsp.py               # LSP client (265 lines)
│   │   │   └── lsp_manager.py       # LSP manager (615 lines)
│   │   │
│   │   ├── vault/                   # Credential vault + auth
│   │   │   ├── __init__.py
│   │   │   ├── credential_vault.py  # AES-256 vault (209 lines)
│   │   │   └── auth.py              # Authentication (147 lines)
│   │   │
│   │   ├── sse/                     # SSE bridge
│   │   │   ├── __init__.py
│   │   │   └── sse_bridge.py        # SSE streaming (132 lines)
│   │   │
│   │   ├── llm_worker/              # Worker process (104 lines)
│   │   ├── mcp_bridge.py            # MCP adapter (588 lines)
│   │   ├── sandbox.py               # Sandbox interface (329 lines)
│   │   ├── sandbox/                 # Sandbox mgr + server (256 lines)
│   │   ├── rpc/                     # RPC protocol + transport (78 lines)
│   │   ├── supervisor.py            # Process supervisor (217 lines)
│   │   ├── cron_scheduler.py        # Cron scheduling (224 lines)
│   │   ├── user_session.py          # User sessions (149 lines)
│   │   ├── notify.py                # Webhooks (99 lines)
│   │   ├── net_client.py            # HTTP client (83 lines)
│   │   ├── network.py               # Network
│   │   ├── ops_console.py           # Dashboard (289 lines)
│   │   ├── ci.py                    # CI pipeline (230 lines)
│   │   ├── git.py                   # Git ops (149 lines)
│   │   └── adapters/
│   │       ├── __init__.py          # Adapter exports (41 lines)
│   │       ├── bus_memory.py        # MemoryBusAdapter (94 lines)
│   │       ├── card_registry.py     # CardRegistryAdapter (40 lines)
│   │       ├── channel_ring.py      # RingChannel (142 lines)
│   │       ├── i18n_yaml.py         # YamlI18nAdapter (138 lines)
│   │       ├── monitor_bus.py       # MonitorBusAdapter (48 lines)
│   │       └── worker_thread.py     # ThreadPoolWorker (198 lines)
│   │
│   ├── l5/                          # === L5: USER ===
│   │   ├── cli.py                   # CLI entry (296 lines)
│   │   └── agent_runtime.py         # Runtime loop (176 lines)
│   │
│   └── services/                    # Empty dir (legacy, files migrated to l2/l3/l4)
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

## API Routes (157 total)

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
| Stats | 3 | `stats/query`, `stats/top`, `stats/live` (SSE) |
| Records | 4 | `records/query`, `records/stats`, `records/export`, `records/bridge` |
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
| `OPENAI_API_KEY` | `ENV_OPENAI_KEY` | `l4/llm/llm_providers.py` |
| `DEEPSEEK_API_KEY` | `ENV_DEEPSEEK_KEY` | `l4/llm/llm_providers.py` |
| `ANTHROPIC_API_KEY` | `ENV_ANTHROPIC_KEY` | `l4/llm/llm_providers.py` |
| `OLLAMA_URL` | `ENV_OLLAMA_URL` | `l4/llm/llm_providers.py` |
| `OLLAMA_MODEL` | `ENV_OLLAMA_MODEL` | `l4/llm/llm_providers.py` |
| `OPENAI_API_URL` | `ENV_OPENAI_URL` | `l4/llm/llm_providers.py` |
| `OPENAI_MODEL` | `ENV_OPENAI_MODEL` | `l4/llm/llm_providers.py` |
| `ANTHROPIC_API_URL` | `ENV_ANTHROPIC_URL` | `l4/llm/llm_providers.py` |
| `ANTHROPIC_MODEL` | `ENV_ANTHROPIC_MODEL` | `l4/llm/llm_providers.py` |
| `LLM_WS_URL` | `ENV_LLM_WS_URL` | `l4/llm/llm_providers.py` |
| `LLM_WS_MODEL` | `ENV_LLM_WS_MODEL` | `l4/llm/llm_providers.py` |
| `NOMOS_SANDBOX_ROOT` | `ENV_SANDBOX_ROOT` | `l4/sandbox.py`, `l3/services/vspace.py` |
| `PRAXIS_DISCOVERY_PORT` | `ENV_DISCOVERY_PORT` | `l3/config/config_handlers.py` |
| `PRAXIS_PORT` | `ENV_PRAXIS_PORT` | `l3/config/config_handlers.py` |
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
