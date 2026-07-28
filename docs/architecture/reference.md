# Praxis Agent OS â€?Reference

> **Audience:** Developers, operators. Reference material, not narrative.  
> **Corresponds to:** actual code tree under `src/`.

## File Layout (complete)

```
praxis/
â”œâ”€â”€ pyproject.toml
â”œâ”€â”€ praxis.yaml
â”œâ”€â”€ .nomos-rules.md
â”œâ”€â”€ commands.yaml                    # 40 command definitions
â”œâ”€â”€ tools.yaml                       # Tool metadata
â”œâ”€â”€ .gitignore
â”?â”œâ”€â”€ src/
â”?  â”œâ”€â”€ l1/kernel/                   # === L1: KERNEL ===
â”?  â”?  â”œâ”€â”€ __init__.py              # Syscall dispatcher (316 lines)
â”?  â”?  â”œâ”€â”€ os.py                    # OS lifecycle (259 lines)
â”?  â”?  â”œâ”€â”€ sync.py                  # Mutex/Semaphore/Barrier/RWLock (421 lines)
â”?  â”?  â”œâ”€â”€ process.py               # ProcessTable + PCB (325 lines)
â”?  â”?  â”œâ”€â”€ allocator.py             # Token allocator + GC (269 lines)
â”?  â”?  â”œâ”€â”€ event.py                 # EventBus pub/sub (161 lines)
â”?  â”?  â”œâ”€â”€ gatechain.py             # G1-G5 authorization (327 lines)
â”?  â”?  â”œâ”€â”€ constitution.py          # Rules engine (465 lines)
â”?  â”?  â”œâ”€â”€ vfs.py                   # Virtual file system (313 lines)
â”?  â”?  â”œâ”€â”€ ipc.py                   # LockChannel + LockBus (137 lines)
â”?  â”?  â”œâ”€â”€ device.py                # Device manager (259 lines)
â”?  â”?  â”œâ”€â”€ persist.py               # SQLite event store (319 lines)
â”?  â”?  â”œâ”€â”€ reputation.py            # Agent trust scores (82 lines)
â”?  â”?  â”œâ”€â”€ tool_chain.py            # Fingerprint chain (303 lines)
â”?  â”?  â”œâ”€â”€ swapper.py               # Ring memory swapper (142 lines)
â”?  â”?  â”œâ”€â”€ settings.py              # Config store proxy (46 lines)
â”?  â”?  â”œâ”€â”€ skill.py                 # Skill manager (258 lines)
â”?  â”?  â”œâ”€â”€ interrupt.py             # Interrupt table (80 lines)
â”?  â”?  â”œâ”€â”€ net.py                   # Network mesh (282 lines)
â”?  â”?  â”œâ”€â”€ net_transport.py         # Transport layer + TLS (282 lines)
â”?  â”?  â”œâ”€â”€ ports.py                 # Port interfaces (335 lines)
â”?  â”?  â”œâ”€â”€ registry.py              # Central system registry (90 lines)
â”?  â”?  â”œâ”€â”€ health.py                # Kernel health check (162 lines)
â”?  â”?  â”œâ”€â”€ resource.py              # Resource limiter (136 lines)
â”?  â”?  â”œâ”€â”€ prompts.py               # Prompt registry (368 lines)
â”?  â”?  â”œâ”€â”€ commands.py              # CommandRegistry â€?sys/user cmds, YAML+API metadata (294 lines)
â”?  â”?  â”œâ”€â”€ model_registry.py        # LLM model registry (298 lines)
â”?  â”?  â”œâ”€â”€ platform.py              # Cross-platform detection (217 lines)
â”?  â”?  â”œâ”€â”€ errors.py                # 20 error codes (208 lines)
â”?  â”?  â”œâ”€â”€ rule_descriptor.py       # Rule definition (106 lines)
â”?  â”?  â”œâ”€â”€ bus.py                   # SystemBus â€?component lifecycle, topology, health (421 lines)
â”?  â”?  â””â”€â”€ versioning.py            # Schema migration (107 lines)
â”?  â”?â”?  â”?  â””â”€â”€ params/                  # === CONSTANTS ===
â”?  â”?      â”œâ”€â”€ __init__.py          # Docstring only â€?no re-exports
â”?  â”?      â”œâ”€â”€ kernel.py            # 154 constants: allocator, sync, gatechain, process, boot
â”?  â”?      â”œâ”€â”€ agent.py             # 181 constants: roles, terminal, loop, card, events, scout
â”?  â”?      â”œâ”€â”€ tool.py              # 39 constants: danger, timeouts, HTN, package mgr
â”?  â”?      â”œâ”€â”€ api.py               # 129 constants: API, LLM, network, IPC, env vars
â”?  â”?      â””â”€â”€ system.py            # 191 constants: cache, memory rings, data paths, truncation
â”?  â”?â”?  â”œâ”€â”€ l2/                          # === L2: SHELL ===
â”?  â”?  â”œâ”€â”€ l2_shell/
â”?  â”?  â”?  â”œâ”€â”€ __init__.py          # dispatch() (105 lines)
â”?  â”?  â”?  â”œâ”€â”€ commands.py          # 39 command handlers (1160 lines)
â”?  â”?  â”?  â”œâ”€â”€ completer.py         # Auto-complete (67 lines)
â”?  â”?  â”?  â”œâ”€â”€ output_guard.py      # Output filtering (22 lines)
â”?  â”?  â”?  â””â”€â”€ state.py             # ShellState (39 lines)
â”?  â”?  â”œâ”€â”€ i18n.py                  # Internationalization (62 lines)
â”?  â”?  â”œâ”€â”€ selector.py              # Agent pre-select (253 lines)
â”?  â”?  â”œâ”€â”€ shell.py                 # Shell entry (199 lines)
â”?  â”?  â”œâ”€â”€ shell_session.py         # Session lifecycle (129 lines)
â”?  â”?  â””â”€â”€ shell_completer.py       # Completion engine (44 lines)
â”?  â”?â”?  â”œâ”€â”€ l3/                          # === L3: CELL ===
â”?  â”?  â”œâ”€â”€ __init__.py              # Root init
â”?  â”?  â”œâ”€â”€ _base.py                 # Base classes (93 lines)
â”?  â”?  â”œâ”€â”€ _persistable.py          # Persistable mixin (104 lines)
â”?  â”?  â”œâ”€â”€ _pool.py                 # Pool utilities (191 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ agent/                   # AgentLoop, Scout, SubAgent (22 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ agent_loop.py        # LLM tool-calling loop (421 lines)
â”?  â”?  â”?  â”œâ”€â”€ agent_persist.py     # Agent persistence
â”?  â”?  â”?  â”œâ”€â”€ ai.py                # AI service (127 lines)
â”?  â”?  â”?  â”œâ”€â”€ convergence.py       # Conventionâ†’Card / convergence detection (156 lines)
â”?  â”?  â”?  â”œâ”€â”€ pal_router.py        # LLM cost router (178 lines)
â”?  â”?  â”?  â”œâ”€â”€ review.py            # Peer review (127 lines)
â”?  â”?  â”?  â”œâ”€â”€ scout.py             # Scout pool (373 lines)
â”?  â”?  â”?  â”œâ”€â”€ session_snapshot.py  # Snapshot lifecycle (69 lines)
â”?  â”?  â”?  â”œâ”€â”€ stagnation.py        # Deadlock detection (195 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent.py          # Lightweight sub-agent (111 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent_dispatcher.py # @mention parsing (92 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent_framework.py # Facade over spec/task/dispatch/merge (115 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent_gate.py     # Card type gate: explore vs execute (72 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent_merger.py   # ResultMerger (58 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent_pool.py     # Async delegation pool, dual-buffer (134 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent_spec.py     # SubAgentSpec dataclass (142 lines)
â”?  â”?  â”?  â”œâ”€â”€ subagent_task.py     # SubAgentTask (AgentLoop execution) (223 lines)
â”?  â”?  â”?  â”œâ”€â”€ verifier.py          # Result verification (120 lines)
â”?  â”?  â”?  â”œâ”€â”€ verify_cadence.py    # Check cadence (97 lines)
â”?  â”?  â”?  â”œâ”€â”€ _term_convention.py  # Terminal convention utilities (126 lines)
â”?  â”?  â”?  â”œâ”€â”€ _term_handlers.py    # Terminal handler logic (339 lines)
â”?  â”?  â”?  â”œâ”€â”€ _term_lifecycle.py   # Terminal lifecycle (51 lines)
â”?  â”?  â”?  â””â”€â”€ _term_types.py       # Terminal types (44 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ agent_terminal/          # Terminal runtime
â”?  â”?  â”?  â””â”€â”€ __init__.py          # AgentTerminal, 34 methods (639 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ boot/                    # Boot sequence + lifecycle (4 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ boot.py              # 7-step system bootstrap (681 lines)
â”?  â”?  â”?  â”œâ”€â”€ lifecycle.py         # Factory reset + singleton reset + disk wipe (200 lines)
â”?  â”?  â”?  â””â”€â”€ wiring.py            # Portâ†’adapter wiring (210 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ bus/                     # IPC, L3B, MonitorBus, HTN (15 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ comm_monitor.py      # Communication monitor (182 lines)
â”?  â”?  â”?  â”œâ”€â”€ htn_a.py             # Global intent sharding
â”?  â”?  â”?  â”œâ”€â”€ htn_b.py             # Inter-cell routing decomposition
â”?  â”?  â”?  â”œâ”€â”€ htn_planner.py       # HTN planner (452 lines)
â”?  â”?  â”?  â”œâ”€â”€ ipc.py               # IPC protocol (323 lines)
â”?  â”?  â”?  â”œâ”€â”€ l3b.py               # L3B: Cross-cell (81 lines)
â”?  â”?  â”?  â”œâ”€â”€ l3b_bus.py           # Composite communication bus (5 message types)
â”?  â”?  â”?  â”œâ”€â”€ l3b_message_pool.py  # 2-tier buffer: Hot Ring + SQLite
â”?  â”?  â”?  â”œâ”€â”€ log.py               # Log service + rotation (288 lines)
â”?  â”?  â”?  â”œâ”€â”€ message_gate.py      # Message policy engine (169 lines)
â”?  â”?  â”?  â”œâ”€â”€ monitor_bus.py       # Monitoring event bus (220 lines)
â”?  â”?  â”?  â”œâ”€â”€ observability_bus.py # Alert/health/metric (143 lines)
â”?  â”?  â”?  â”œâ”€â”€ reference_channel.py # Event capture (260 lines)
â”?  â”?  â”?  â””â”€â”€ task_bus.py          # Task dispatch (220 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ card/                    # Card lifecycle + registry (21 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ approval_gate.py     # Human approval (155 lines)
â”?  â”?  â”?  â”œâ”€â”€ card_builder.py      # Intentâ†’Card compiler (227 lines)
â”?  â”?  â”?  â”œâ”€â”€ card_gate.py         # Card approval gate (252 lines)
â”?  â”?  â”?  â”œâ”€â”€ card_pool.py         # Remote card registry (183 lines)
â”?  â”?  â”?  â”œâ”€â”€ card_registry.py     # Card queue + status (490 lines)
â”?  â”?  â”?  â”œâ”€â”€ card_registry_protocol.py # Net protocol (80 lines)
â”?  â”?  â”?  â”œâ”€â”€ card_unified.py      # Unified card types (550 lines)
â”?  â”?  â”?  â”œâ”€â”€ card_yaml.py         # YAML card loader (58 lines)
â”?  â”?  â”?  â”œâ”€â”€ convention.py        # Convention meetings (280 lines)
â”?  â”?  â”?  â”œâ”€â”€ decomposer.py        # Intent decomposition (265 lines)
â”?  â”?  â”?  â”œâ”€â”€ dialogue_session.py  # Dialogue persistence (325 lines)
â”?  â”?  â”?  â”œâ”€â”€ execution_engine.py  # Step execution (386 lines)
â”?  â”?  â”?  â”œâ”€â”€ execution_plan.py    # Cardâ†’Plan compiler (613 lines)
â”?  â”?  â”?  â”œâ”€â”€ execution_run.py     # Execution runner
â”?  â”?  â”?  â”œâ”€â”€ execution_verify.py  # Verification chain (96 lines)
â”?  â”?  â”?  â”œâ”€â”€ issue.py             # Issue tracking (286 lines)
â”?  â”?  â”?  â”œâ”€â”€ models.py            # Card model types
â”?  â”?  â”?  â”œâ”€â”€ pending_queue.py     # Approval queue (270 lines)
â”?  â”?  â”?  â”œâ”€â”€ plan_step_types.py   # Plan step data (38 lines)
â”?  â”?  â”?  â””â”€â”€ transaction_area.py  # Card staging (302 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ cell/                    # Cell class + components + peers (22 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py          # Cell class, 28+ methods (1048 lines)
â”?  â”?  â”?  â”œâ”€â”€ components/
â”?  â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_agent.py    # Agent registration
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_buffer.py   # CircularBuffer (65 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_cache.py    # L2 shared cache (383 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_convention.py # Cell convention helpers (139 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_cross_review.py # Cross-review
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_decompose.py # Cell decomposition (101 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_execute.py  # Cell execution
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_icache.py   # ICache, LFU (168 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_interrupt.py # InterruptController, 4 pri (249 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_mmu.py      # CellMmu + CellTlb (209 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_monitor.py  # Cell health events (209 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_pmu.py      # 28 performance counters (199 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_rollback.py # Cell rollback
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_token_merger.py # Token tracking (68 lines)
â”?  â”?  â”?  â”?  â”œâ”€â”€ cell_types.py    # Cell type definitions (100 lines)
â”?  â”?  â”?  â”?  â””â”€â”€ cell_watchdog.py # Watchdog timer (187 lines)
â”?  â”?  â”?  â””â”€â”€ peers/
â”?  â”?  â”?  â”œâ”€â”€ __init__.py          # Lazy-import facades (34 lines)
â”?  â”?  â”?      â”œâ”€â”€ central_collector.py # Token aggregation (149 lines)
â”?  â”?  â”?      â”œâ”€â”€ l3.py            # L3 coordinator (224 lines)
â”?  â”?  â”?      â””â”€â”€ l3a.py           # L3A: Humanâ†’Card (212 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ config/                  # Config loading + settings (8 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ bootstrap.py         # YAML bootstrap wizard (329 lines)
â”?  â”?  â”?  â”œâ”€â”€ cache_strategy.py    # LLM prefix cache (107 lines)
â”?  â”?  â”?  â”œâ”€â”€ config.py            # Config API (111 lines)
â”?  â”?  â”?  â”œâ”€â”€ config_handlers.py   # Config migration (305 lines)
â”?  â”?  â”?  â”œâ”€â”€ config_loader.py     # praxis.yaml loader (282 lines)
â”?  â”?  â”?  â”œâ”€â”€ settings_adapter.py  # Settings adapter (67 lines)
â”?  â”?  â”?  â””â”€â”€ settings_center.py   # 3-layer settings (247 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ error_bus/               # Error capture bus (2 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py          # ErrorBus, error_boundary (725 lines)
â”?  â”?  â”?  â””â”€â”€ api.py               # 6 API handlers (72 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ memory/                  # 4-ring memory + pager + cache (17 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ archive_orchestrator.py # Archive (104 lines)
â”?  â”?  â”?  â”œâ”€â”€ cache.py             # Multi-level cache (301 lines)
â”?  â”?  â”?  â”œâ”€â”€ cache_doc.py         # Meeting doc cache (151 lines)
â”?  â”?  â”?  â”œâ”€â”€ central_memory.py    # R1-R4 coordinator (165 lines)
â”?  â”?  â”?  â”œâ”€â”€ context.py           # Context register (181 lines)
â”?  â”?  â”?  â”œâ”€â”€ context_pool.py      # Per-agent context pool (76 lines)
â”?  â”?  â”?  â”œâ”€â”€ memory.py            # MemoryManager â€?4-ring (536 lines)
â”?  â”?  â”?  â”œâ”€â”€ memory_context.py    # Memory context
â”?  â”?  â”?  â”œâ”€â”€ memory_init.py       # Memory lifecycle (318 lines)
â”?  â”?  â”?  â”œâ”€â”€ memory_quality.py    # Quality scoring (92 lines)
â”?  â”?  â”?  â”œâ”€â”€ memory_ring.py       # RingLayer, MemEntry (153 lines)
â”?  â”?  â”?  â”œâ”€â”€ memory_search.py     # Memory search
â”?  â”?  â”?  â”œâ”€â”€ pager.py             # Context paging (320 lines)
â”?  â”?  â”?  â”œâ”€â”€ pager_bridge.py      # Swapperâ†”Pager bridge (106 lines)
â”?  â”?  â”?  â”œâ”€â”€ r4_agent.py          # R4 archivist (443 lines)
â”?  â”?  â”?  â””â”€â”€ result_store.py      # Tool result cache (163 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ resource_buffer/         # Ring file buffer (4 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ api.py               # Buffer API handlers (36 lines)
â”?  â”?  â”?  â”œâ”€â”€ manager.py           # ResourceBufferManager (62 lines)
â”?  â”?  â”?  â””â”€â”€ ring.py              # RingBuffer (290 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ scheduler/               # 5-D scheduler + think + ACB (11 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ acb.py               # Agent Control Block (332 lines)
â”?  â”?  â”?  â”œâ”€â”€ loop_detectors.py    # Loop detection (84 lines)
â”?  â”?  â”?  â”œâ”€â”€ scheduler.py         # Unified scheduler (177 lines)
â”?  â”?  â”?  â”œâ”€â”€ scheduler_rate.py    # Rate scheduler (72 lines)
â”?  â”?  â”?  â”œâ”€â”€ scheduler_router.py  # Intent routing (118 lines)
â”?  â”?  â”?  â”œâ”€â”€ scheduler_scope.py   # Scope scheduling (75 lines)
â”?  â”?  â”?  â”œâ”€â”€ scheduler_time.py    # Time-slice (126 lines)
â”?  â”?  â”?  â”œâ”€â”€ scheduler_types.py   # Dataclasses (57 lines)
â”?  â”?  â”?  â”œâ”€â”€ sequence_monitor.py  # Anomaly detection (263 lines)
â”?  â”?  â”?  â””â”€â”€ think_registry.py    # Think quota registry (247 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ services/                # Stats, Records, Model, etc. (29 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ assembly.py          # Constitutional assembly (212 lines)
â”?  â”?  â”?  â”œâ”€â”€ bus_components.py    # Bus component registration
â”?  â”?  â”?  â”œâ”€â”€ cell_orchestrate.py  # SubAgentOrchestrator (fork-join via SubAgentPool) (234 lines)
â”?  â”?  â”?  â”œâ”€â”€ central_plugin.py    # Plugin lifecycle (152 lines)
â”?  â”?  â”?  â”œâ”€â”€ central_security.py  # 6-gate check (166 lines)
â”?  â”?  â”?  â”œâ”€â”€ content_trust.py     # Content provenance (367 lines)
â”?  â”?  â”?  â”œâ”€â”€ counter.py           # Token/tool/turn counters (321 lines)
â”?  â”?  â”?  â”œâ”€â”€ fault_tolerance.py   # Checkpoint + recovery (323 lines)
â”?  â”?  â”?  â”œâ”€â”€ file_editor.py       # Semantic file editing (671 lines)
â”?  â”?  â”?  â”œâ”€â”€ fs.py                # Filesystem ops (199 lines)
â”?  â”?  â”?  â”œâ”€â”€ global_components.py # Global component registration
â”?  â”?  â”?  â”œâ”€â”€ hook.py              # Hook system
â”?  â”?  â”?  â”œâ”€â”€ identity.py          # Ed25519 keys + proofs (391 lines)
â”?  â”?  â”?  â”œâ”€â”€ middleware.py        # Service middleware
â”?  â”?  â”?  â”œâ”€â”€ model_service.py     # ModelService â€?ModelSpec resolution (542 lines)
â”?  â”?  â”?  â”œâ”€â”€ package_manager.py   # Unified apt/pip/npm/cargo (175 lines)
â”?  â”?  â”?  â”œâ”€â”€ process.py           # Process manager (139 lines)
â”?  â”?  â”?  â”œâ”€â”€ prompt_engine.py     # Prompt building (469 lines)
â”?  â”?  â”?  â”œâ”€â”€ record_center.py     # Unified record center (358 lines)
â”?  â”?  â”?  â”œâ”€â”€ service_manager.py   # Service lifecycle (220 lines)
â”?  â”?  â”?  â”œâ”€â”€ session_export.py    # Session export (340 lines)
â”?  â”?  â”?  â”œâ”€â”€ statecharts.py       # 5-region state machine (301 lines)
â”?  â”?  â”?  â”œâ”€â”€ stats_center.py      # Cross-Cell metric aggregation (341 lines)
â”?  â”?  â”?  â”œâ”€â”€ template.py          # Jinja2 templates (85 lines)
â”?  â”?  â”?  â”œâ”€â”€ todo.py              # Task queue (202 lines)
â”?  â”?  â”?  â”œâ”€â”€ todo_tracker.py      # Todo state machine (240 lines)
â”?  â”?  â”?  â”œâ”€â”€ vspace.py            # Virtual space (311 lines)
â”?  â”?  â”?  â””â”€â”€ workspace.py         # Workspace manager (86 lines)
#   â”?  â”?  â”?  â”œâ”€â”€ model_strategy.py    # ModelStrategyEngine, three-layer think config + CapabilityDetector (async probe pool)
#   â”?  â”?  â”?  â”œâ”€â”€ approval_policy.py   # ApprovalPolicy, three-layer danger level override
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ tool_system/             # Tool pipeline + spec + policy (8 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ tool_config.py       # YAML tool config (250 lines)
â”?  â”?  â”?  â”œâ”€â”€ tool_mode.py         # Global read/write mode (101 lines)
â”?  â”?  â”?  â”œâ”€â”€ tool_params.py       # Tool parameter definitions
â”?  â”?  â”?  â”œâ”€â”€ tool_pipeline.py     # 9-step execution (295 lines)
â”?  â”?  â”?  â”œâ”€â”€ tool_policy.py       # Tool visibility policy (241 lines)
â”?  â”?  â”?  â”œâ”€â”€ tool_registry.py     # ToolRegistry class (MapRegistry-backed, 280 lines)
â”?  â”?  â”?  â””â”€â”€ tool_spec.py         # ToolSpec registry (546 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ tools/                     # 17 tool implementations
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ discussion/                # Multi-Cell discussion + convergence (7 files)
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ cell_answer_repo.py    # Per-Cell answer persistence (245 lines)
â”?  â”?  â”?  â”œâ”€â”€ answer_session.py      # 5-phase answer protocol (308 lines)
â”?  â”?  â”?  â”œâ”€â”€ issue_orchestrator.py  # Issueâ†’discussion orchestration (225 lines)
â”?  â”?  â”?  â”œâ”€â”€ answer_aggregator.py   # Cross-Cell merge + dedup + divergence (284 lines)
â”?  â”?  â”?  â”œâ”€â”€ supplement_manager.py  # Supplement classify/route (113 lines)
â”?  â”?  â”?  â””â”€â”€ report_service.py      # Report â†?MD + L3A + SSE (149 lines)
â”?  â”?  â”?â”?  â”?â”?  â”œâ”€â”€ l4/                          # === L4: BRIDGE ===
â”?  â”?  â”œâ”€â”€ api/                     # HTTP gateway + routes + middleware
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ api_gateway.py       # HTTP server (393 lines)
â”?  â”?  â”?  â”œâ”€â”€ api_routes.py        # 170 routes (234 lines)
â”?  â”?  â”?  â”œâ”€â”€ api_middleware.py    # Middleware chain (312 lines)
â”?  â”?  â”?  â””â”€â”€ api_handlers_cards.py # Card handlers (93 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ api_handlers/            # 11 handler modules
â”?  â”?  â”?  â”œâ”€â”€ __init__.py          # Handler mixin (770 lines)
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_agent.py # Agent handlers (83 lines)
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_cluster.py # Cluster handlers
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_commands.py # Command handlers
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_config.py # Config handlers (168 lines)
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_constitution.py # Constitution API (73 lines)
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_discussion.py # Discussion API (8 routes)
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_monitor.py # Monitor handlers (188 lines)
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_providers.py # Provider + model-spec API (18 routes)
â”?  â”?  â”?  â”œâ”€â”€ api_handlers_records.py # RecordCenter query/stats/export (91 lines)
â”?  â”?  â”?  â””â”€â”€ api_handlers_stats.py   # StatsCenter query/top/live (101 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ llm/                     # LLM engine + providers
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ llm.py               # LLM Engine (590 lines)
â”?  â”?  â”?  â”œâ”€â”€ llm_base.py          # LLMProvider ABC (223 lines)
â”?  â”?  â”?  â””â”€â”€ llm_providers.py     # Provider impls (299 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ search/                  # Search engine
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ search.py            # Text search (124 lines)
â”?  â”?  â”?  â””â”€â”€ search_engine.py     # Full-text search (556 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ lsp/                     # LSP client + manager
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ lsp.py               # LSP client (265 lines)
â”?  â”?  â”?  â””â”€â”€ lsp_manager.py       # LSP manager (615 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ vault/                   # Credential vault + auth
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â”œâ”€â”€ credential_vault.py  # AES-256 vault (209 lines)
â”?  â”?  â”?  â””â”€â”€ auth.py              # Authentication (147 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ sse/                     # SSE bridge
â”?  â”?  â”?  â”œâ”€â”€ __init__.py
â”?  â”?  â”?  â””â”€â”€ sse_bridge.py        # SSE streaming (132 lines)
â”?  â”?  â”?â”?  â”?  â”œâ”€â”€ llm_worker/              # Worker process (104 lines)
â”?  â”?  â”œâ”€â”€ mcp_bridge.py            # MCP adapter (588 lines)
â”?  â”?  â”œâ”€â”€ sandbox.py               # Cell COW sandbox (329 lines)
â”?  â”?  â”œâ”€â”€ sandbox/                 # Execution sandbox: manager + server (256 lines)
â”?  â”?  â”œâ”€â”€ rpc/                     # RPC protocol + transport (78 lines)
â”?  â”?  â”œâ”€â”€ supervisor.py            # Process supervisor (222 lines)
â”?  â”?  â”œâ”€â”€ cron_scheduler.py        # Cron scheduling (224 lines)
â”?  â”?  â”œâ”€â”€ user_session.py          # User sessions (149 lines)
â”?  â”?  â”œâ”€â”€ notify.py                # Webhooks (99 lines)
â”?  â”?  â”œâ”€â”€ net_client.py            # HTTP client (83 lines)
â”?  â”?  â”œâ”€â”€ network.py               # Network mesh
â”?  â”?  â”œâ”€â”€ ops_console.py           # Dashboard (289 lines)
â”?  â”?  â”œâ”€â”€ ci.py                    # Internal CI pipeline (231 lines)
â”?  â”?  â”œâ”€â”€ git.py                   # Git ops (149 lines)
â”?  â”?  â””â”€â”€ adapters/
â”?  â”?      â”œâ”€â”€ __init__.py          # Adapter exports (41 lines)
â”?  â”?      â”œâ”€â”€ bus_memory.py        # MemoryBusAdapter (94 lines)
â”?  â”?      â”œâ”€â”€ card_registry.py     # CardRegistryAdapter (40 lines)
â”?  â”?      â”œâ”€â”€ channel_ring.py      # RingChannel (142 lines)
â”?  â”?      â”œâ”€â”€ i18n_yaml.py         # YamlI18nAdapter (138 lines)
â”?  â”?      â”œâ”€â”€ monitor_bus.py       # MonitorBusAdapter (48 lines)
â”?  â”?      â””â”€â”€ worker_thread.py     # ThreadPoolWorker (198 lines)
â”?  â”?â”?  â”œâ”€â”€ l5/                          # === L5: USER ===
â”?  â”?  â”œâ”€â”€ cli.py                   # CLI entry (296 lines)
â”?  â”?  â””â”€â”€ agent_runtime.py         # Runtime loop (176 lines)
â”?  â”?â”?  â”œâ”€â”€ main.py                      # REPL + dispatch entry point
â”?  â”œâ”€â”€ tool_ring.py                 # Per-agent tool ring + request pool
â”?  â”œâ”€â”€ tool_approval.py             # Ring 3 approval/witness
â”?  â””â”€â”€ services/                    # Empty dir (legacy, files migrated to l2/l3/l4)
â”?â”œâ”€â”€ tests/
â”?  â”œâ”€â”€ test_layer_imports.py        # Layer constraint enforcement
â”?  â”œâ”€â”€ test_params_integrity.py     # 17 tests â€?constant integrity
â”?  â”œâ”€â”€ test_kernel.py               # 26 tests â€?kernel modules
â”?  â”œâ”€â”€ test_services_core.py        # 21 tests â€?services
â”?  â”œâ”€â”€ test_api_routes.py           # 19 tests â€?route matching
â”?  â””â”€â”€ ...
â”?â””â”€â”€ docs/
    â”œâ”€â”€ architecture/
    â”?  â”œâ”€â”€ overview.md              # This directory root
    â”?  â”œâ”€â”€ reference.md             # This file
    â”?  â””â”€â”€ deep-dive/               # Detailed subsystem docs
    â”?      â”œâ”€â”€ boot-sequence.md
    â”?      â”œâ”€â”€ gatechain.md
    â”?      â”œâ”€â”€ memory.md
    â”?      â”œâ”€â”€ tool-pipeline.md
    â”?      â”œâ”€â”€ cell-agent.md
    â”?      â”œâ”€â”€ card-lifecycle.md
    â”?      â””â”€â”€ security.md
#   â”?      â”œâ”€â”€ buses-and-control.md
#   â”?      â””â”€â”€ cross-cell-htn.md
    â””â”€â”€ design/
```

## Constants Reference

### `params/kernel.py` (154 constants)

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
| Syscall | `SYSCALL_AUDIT_MAX=5000`, `SYSCALL_AUDIT_CLI_LIMIT=50` |
| Stagnation | `STAGNATION_SPIN_THRESHOLD=3` |
| Watchdog | `WATCHDOG_INTERVAL=15`, `WATCHDOG_ZOMBIE_LIMIT=3`, `WATCHDOG_IDLE_LIMIT=300` |
| Boot | `BOOT_STEP_TIMEOUT=60.0` |
| Ring | `RING_1`, `RING_2_5`, `RING_3` + `RING_NUM_MAP` + `RING_NAME_MAP` |
| GateStatus | `PASS`, `WARN`, `BLOCK`, `REPORT` |
| WitnessStatus | `PENDING`, `APPROVED`, `REJECTED` |

### `params/agent.py` (181 constants)

| Section | Key Constants |
|---------|--------------|
| Constitution | `BUILTIN_RULE_DEFS` (15 rules), `CONSTITUTION_FILE_ACTIONS`, `CONSTITUTION_MODIFY_ACTIONS`, `CONSTITUTION_SCOUT_BLOCKED` |
| Agent | `AgentDefaults`, `DEFAULT_AGENT_CONFIGS`, `CENTRAL_ROLES`, `AGENT_CLEARANCE` |
| Terminal | `TERMINAL_MODE_VALID=("assembly","direct")`, `TERMINAL_CONTEXT_RECENT=5`, `TERMINAL_OUTPUT_MAX_CHARS=4000` |
| Loop | `AGENT_LOOP_DEFAULT_STEPS=10`, `AGENT_LOOP_DEFAULT_TIMEOUT=120.0`, `AGENT_LOOP_MAX_WORKERS=4` |
| Scout | `SCOUT_LOOP_STEPS=10`, `SCOUT_LOOP_TIMEOUT=180.0`, `SCOUT_FINDING_TRUNC=500`, `SCOUT_FILE_READ_TRUNC=4000`, `SCOUT_GREP_MAX=20` |
| SubAgent | `SUBAGENT_LOOP_STEPS=5`, `SUBAGENT_LOOP_TIMEOUT=30.0`, `SUBAGENT_MAX_TOKENS=4096` |
| Events | `EVENT_TASK_ASSIGN`, `EVENT_REVIEW_REQUESTED`, `EVENT_TOKEN_USAGE`, `EVENT_CROSS_REVIEW`, `EVENT_AGENT_BOOT`, `EVENT_ARCHIVE_ALERT` |
| Card | `CARD_TIMEOUT=30.0`, `CARD_WAIT_TIMEOUT=30.0`, `CARD_GATE_APPROVAL_TIMEOUT=3600.0`, `CARD_BUILDER_MODES` |
| Cell | `CELL_ROLLBACK_RING_SIZE=20`, `CELL_MAILBOX_MAX_PER_AGENT=100` |
| Agent Status | `AGENT_STATUS_IDLE`, `AGENT_STATUS_PROCESSING`, `AGENT_STATUS_CRASHED`, `AGENT_STATUS_BOOTING` |

### `params/tool.py` (39 constants)

| Section | Key Constants |
|---------|--------------|
| Danger | `TOOL_DANGER_LEVEL` {0-3}, `DANGER_TO_GATES` |
| Timeouts | `TOOL_BUILD_TIMEOUT=300`, `TOOL_PIP_INSTALL_TIMEOUT=120`, `TOOL_GIT_TIMEOUT=30`, `TOOL_TERMINAL_TIMEOUT=30.0`, `TOOL_GREP_TIMEOUT=15.0`, `TOOL_PACKAGE_MANAGER_TIMEOUT=120` |
| Rates | `TOOL_RATE_RING_1=60/min`, `TOOL_RATE_RING_2_5=20/min`, `TOOL_RATE_RING_3=5/min` |
| HTN | `HTN_DEFAULT_TOOLS` (14 tool mappings) |
| Build | `BUILD_DETECTORS` (pip/cargo/npm/msbuild/dotnet), `TEST_DETECTORS` (pytest/cargo/npm/dotnet/vstest) |

### `params/api.py` (129 constants)

| Section | Key Constants |
|---------|--------------|
| PAL | `PAL_FRUGAL_COST=1`, `PAL_STANDARD_COST=10`, `PAL_FRONTIER_COST=30` |
| LLM | `LLM_RATE_LIMIT_WAIT=60`, `LLM_PROVIDER_URLS` (openai/anthropic/ollama/deepseek) |
| API | `API_GATEWAY_PORT=8080`, `API_GATEWAY_HOST="127.0.0.1"`, `API_MAX_BODY_BYTES`, API_CORS_* |
| Network | `BROADCAST_INTERVAL=15.0`, `PEER_TIMEOUT=60.0`, `DISCOVERY_PORT_DEFAULT=42069`, `MESH_PORT_DEFAULT=42070` |
| IPC | `IPC_SOCKET_DIR`, `IPC_KERNEL_SOCKET`, `IPC_LLM_SOCKET`, `IPC_SANDBOX_SOCKET` |
| Env Vars | `ENV_OPENAI_KEY`, `ENV_ANTHROPIC_KEY`, `ENV_SANDBOX_ROOT`, `ENV_DEEPSEEK_KEY`, `ENV_OLLAMA_URL`, `ENV_API_TOKEN` (18 total) |
| Channel | `CHANNEL_RING_CAPACITY=1024` |
| Worker | `WORKER_POOL_MIN=4`, `WORKER_POOL_MAX=32` |
| SubAgent | `SUBAGENT_RUN_TIMEOUT=120.0`, `SUBAGENT_JOIN_TIMEOUT=30.0` |
| Transport | `TRANSPORT_SOCKET_TIMEOUT=10.0` |

### `params/system.py` (194 constants)

| Section | Key Constants |
|---------|--------------|
| Cache | `FILE_CACHE_MAX_ENTRIES=500`, `FILE_CACHE_TTL=60.0`, `CELL_CACHE_HOT_SIZE=50` |
| Scout Pool | `SCOUT_POOL_MAX_TOTAL=16`, `SCOUT_POOL_IDLE_TIMEOUT=60.0`, `SCOUT_CACHE_TTL=30.0`, `SCOUT_POOL_MAX_PER_AGENT=4` |
| Persistence | `PERSIST_INTERVAL=30.0`, `CARD_REGISTRY_AUTO_SAVE=30.0`, `CARD_GATE_AUTO_SAVE=10.0` |
| Memory Ring | `RING1_CAPACITY=32`, `RING2_CAPACITY=200`, `RING3_CAPACITY=1000` |
| Memory Budget | `MEMORY_RING_WORKING_BUDGET=8192`, `MEMORY_RING_SHORT_BUDGET=32768`, `MEMORY_RING_LONG_BUDGET=131072` |
| Memory Importance | `MEMORY_IMPORTANCE_BASE=0.5`, `MEMORY_PRESSURE_HIGH=0.80`, `MEMORY_PROMOTION_THRESHOLD=0.6` |
| Polling | `POLL_INTERVAL_FAST=0.01`, `POLL_INTERVAL_SLOW=0.05`, `POLL_INTERVAL_PAUSED=0.5` |
| Sandbox | `SANDBOX_PROFILE_READ_ONLY="DANGER_0"`, `SANDBOX_EXEC_TIMEOUT=300.0`, `SANDBOX_MAX_OUTPUT=5000` |
| Truncation | `LOG_TRUNC_40` through `LOG_TRUNC_10000` (15 values), `HASH_TRUNC_SHORT=8`, `HASH_TRUNC_MEDIUM=12`, `HASH_TRUNC_LONG=16` |
| Token | `TOKEN_CELL_QUOTA=5_000_000`, `TOKEN_GLOBAL_QUOTA=50_000_000` |
| Error Bus | `ERROR_BUS_BUFFER=5000`, `ERROR_BUS_DEDUP_WINDOW=300` |
| Log | `LOG_MAX_MEMORY_ENTRIES=5000`, `LOG_EXPORT_LIMIT=10000` |
| Think | `THINK_BUDGET_GLOBAL_DEFAULT=0`, `THINK_REASONING_DEFAULT="none"` |
| PMU | `PMU_HISTORY_SIZE=3600`, `PMU_SNAPSHOT_INTERVAL=60.0` |
| ICache | `ICACHE_MAX_ENTRIES=500`, `ICACHE_TTL=3600.0`, `ICACHE_LFU_DECAY=0.95` |
| Interrupt | `IRQ_TABLE_SIZE=32`, `IRQ_PRIORITY_LEVELS=4` |
| Stats | `STATS_BUCKET_SIZE=600`, `STATS_HISTORY_BUCKETS=144` |
| Version | `KERNEL_VERSION="0.3.0"`, `PRAXIS_CODENAME="Aether"` |

## API Routes (208 total)

| Category | Routes | Handler Prefix |
|----------|--------|---------------|
| Core | 8 | `health`, `processes`, `devices`, `settings`, `syscalls`, `peers`, `list_endpoints`, `endpoints` |
| Cards | 10 | `list_cards`, `get_card`, `submit_card`, `submit_batch`, `card_rollback`, `card_approval_trail`, `card_unified_submit`, `card_plan`, `sideload_dispatch`, `card_gate_history` |
| Card Gate | 4 | `card_gate_stats`, `card_gate_config`, `card_gate_config_set`, `card_types_list` |
| Card Types | 2 | `card_types_list`, `card_types_register` |
| Approvals | 4 | `list_approvals`, `approval_respond`, `gate_pending`, `gate_respond` |
| Pending | 6 | `pending_list`, `pending_approve`, `pending_reject`, `pending_escalate`, `pending_priority`, `pending_stats` |
| Cell/Cluster | 4 | `cell_stop`, `cell_liveness`, `cluster_status`, `cluster_expand`, `cluster_shrink` |
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
| Constitution | 5 | `constitution`, `constitution/rules`, `constitution/summary`, `constitution/reload`, `constitution/custom` |
| Bootstrap | 3 | `bootstrap_status`, `bootstrap_defaults`, `bootstrap_apply` |
| **System Lifecycle** | **6** | **`boot`, `shutdown`, `reboot`, `reload`, `reset`, `boot/status`** |
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
| Session Export | 6 | `export`, `import`, `snapshots`, `snapshot`, `snapshot/restore`, `snapshot/delete` |
| SSE | 1 | `events` |
| Buffer | 4 | `buffer/status`, `buffer/commit`, `buffer/diff`, `buffer/discard` |
| Monitor | 6 | `monitor/events`, `monitor/stats`, `monitor/stream`, `monitor/gate`, `monitor/gate/<id>` |
| Stats | 3 | `stats/query`, `stats/top`, `stats/live` (SSE) |
| Records | 4 | `records/query`, `records/stats`, `records/export`, `records/bridge` |
| Discussion | 8 | `discussion/submit_issue`, `discussion/session`, `discussion/session/<id>`, `discussion/cell`, `/v2/discussion/abort`, `/v2/discussion/sessions`, `/v2/discussion/aggregate`, `/v2/discussion/report` |
| Loop | 2 | `loop_config`, `loop_config` |
| Agent Config | 2 | `agent/config`, `agent/config` |
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

## Layer Import Allowlist (53 entries)

Pre-existing cross-layer imports exempted from the strict one-way rule in `test_layer_imports.py`. The full allowlist has 172 tuple entries but many are duplicates caused by refactoring (commands.py split into session/system/control/agent sub-files). Unique source-target pairs:

| Pattern | Unique Pairs | Reason |
|---------|-------------|--------|
| L1 â†?L3/L4 | 6 | Adapter ports (settingsâ†’adapter, netâ†’worker/channel), OS fallback lifecycle imports |
| L2 â†?L3/L4 | 3 | Shell accessing L3 services + i18n adapter |
| L3 â†?L4 (LLM) | 6 | AgentLoop, cache, card_registry etc. need LLM |
| L3 â†?L4 (adapters) | 6 | wiring.py boot-time port assembly |
| L3 â†?L4 (services) | 4 | Config handlers, prompt engine, sandbox, notify |
| L2 â†?L3 | 24 | Shell commands accessing cell, memory, scheduler, security, plugin services |
| L1 â†?L4 | 1 | model_registry needs LLM base |

## Environment Variables (~16 total, some only partially populated at runtime)

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
| `NOMOS_DEFAULT_CELL` | `ENV_DEFAULT_CELL` | â€?|
| `PRAXIS_API_TOKEN` | `ENV_API_TOKEN` | â€?|

## State File Paths (25+)

Persistent state is stored in the project root directory (CWD), not under `PRAXIS_DATA_DIR`:

| Pattern / File | Contents | Generated By |
|----------------|----------|-------------|
| `.praxis_state.db` | SQLite event store | `l1/kernel/persist.py` |
| `.praxis_card_registry.json` | Card queue + status | `l3/card/card_registry.py` |
| `.praxis_pending_queue.json` | Approval queue | `l3/card/pending_queue.py` |
| `.praxis_approval_gate.json` | Approval gate state | `l3/card/approval_gate.py` |
| `.praxis_settings.json` | Runtime settings overrides | `l3/config/settings_center.py` |
| `.praxis_sandbox_state.json` | COW sandbox state | `l4/sandbox.py` |
| `.praxis_todo_table.json` | Task queue | `l3/services/todo.py` |
| `.praxis_execution_results.json` | Card execution results | `l3/card/execution_engine.py` |
| `.praxis_dialogue_session.json` | Dialogue persistence | `l3/card/dialogue_session.py` |
| `*.chain_key` | Tool call fingerprints | `l1/kernel/tool_chain.py` |
| `memories/` | Agent memory directory | `l3/memory/` |
| `memories/AGENT/sessions/` | Boot/shutdown snapshots | `l3/memory/memory_init.py` |
| `memories/archives/` | R4 agent archives | `l3/memory/r4_agent.py` |
| `memories/archive.db` | Long-term memory (SQLite FTS5) | `l3/memory/memory.py` |
| `events.db` | Event store (legacy) | `l1/kernel/persist.py` |
| `.praxis_seq_monitor_*.json` | Sequence anomaly data | `l3/scheduler/sequence_monitor.py` |
| `.praxis_monitor_bus.jsonl` | Monitor event log | `l3/bus/monitor_bus.py` |
| `.praxis/.praxis_reference_channel.jsonl` | Reference channel events | `l3/bus/reference_channel.py` |

Factory reset (`lifecycle.py:wipe_disk_state()`) deletes all of these files.
