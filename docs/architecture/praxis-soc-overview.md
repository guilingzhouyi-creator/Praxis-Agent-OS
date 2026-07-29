# Praxis Agent OS — System-on-Chip Overview

> **Status map:** ✅ Complete / ◐ Partial / ⬜ Not Started / 🔧 Uncommitted

## L1 Kernel — 37 files, 8,497 lines ✅

```
┌─────────────────────────────────────────────────────────────────────┐
│  L1 Kernel Layer                                                    │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ sync.py  │ │process.py│ │allocator │ │ event.py │ │gatechain │ │
│  │ Mutex/Sem│ │ PCB/PTbl │ │ Token GC │ │ EventBus │ │ G1-G5 ✅ │ │
│  │ Barrier  │ ✅        │ ✅        │ ✅       │ ✅       │
│  ✅         │          │          │          │          │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤ │
│  │constitutn│ │ vfs.py   │ │ ipc.py   │ │ device.py│ │ net.py   │ │
│  │ RulesEng │ │ Ring VFS │ │ LockChan │ │ DevMgr   │ │ UDP/TCP  │ │
│  │ ✅      │ ✅       │ ✅       │ ✅       │ ✅       │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤ │
│  │ persist  │ │reputation│ │ tool_chn │ │ commands │ │ prompts  │ │
│  │ SQLite   │ │ TrustScr │ │ HMAC-SHA │ │ CmdReg   │ │ PromptTm │ │
│  │ ✅      │ ✅       │ ✅       │ ✅       │ ✅       │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤ │
│  │ os.py    │ │ errors   │ │ ports.py │ │ platform │ │ params/  │ │
│  │ Lifecycle│ │ 20 codes │ │ 7 interfc│ │ CrossPlat│ │ 589 cons │ │
│  │ ✅      │ ✅       │ ✅       │ ✅       │ ✅       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Status: ✅ Complete.** L1 is the most polished layer with no known gaps. `commands.py` now exports `CommandRegistry` class with system (38 built-in, protected) vs user command separation, 3-layer metadata (commands.yaml → praxis.yaml → API runtime).

## L2 Shell — 10 files, 1,977 lines ✅

```
┌─────────────────────────────────────────────────────────────────────┐
│  L2 Shell Layer                                                     │
│                                                                     │
│  ┌──────────────────┐ ┌────────────────┐ ┌──────────────────────┐ │
│  │ l2_shell/        │ │ i18n.py        │ │ selector.py          │ │
│  │ 39 commands      │ │ I18nPort       │ │ Agent pre-select    │ │
│  │ pipeline |       │ │ YamlI18nAdapt  │ │ connectivity check  │ │
│  │ dispatch() ✅    │ │ ✅            │ │ ✅                  │ │
│  ├──────────────────┤ ├────────────────┤ ├──────────────────────┤ │
│  │ shell.py         │ │ shell_session  │ │ shell_completer.py  │ │
│  │ Shell entry      │ │ Session mgmt   │ │ Auto-completion     │ │
│  │ ✅              │ │ ✅            │ │ ✅                  │ │
│  └──────────────────┘ └────────────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Status: ✅ Complete.** 39 commands + pipeline + scope resolution + i18n.

## L3 Cell — 154+ files, ~32,800 lines

### PMU — Performance Monitoring Unit ✅

```
┌──────────────────────────────────────────────────────────────┐
│  PMU — CellPmu (src/l3/cell/components/cell_pmu.py, 236L)                    │
│                                                              │
│  28 hardware-style 64-bit counters per Cell, dot-delimited:  │
│                                                              │
│  cards.dispatched/completed/failed/rolled_back/decomposed    │
│  tools.executed.ring_{1,2_5,3} / tools.rejected             │
│  cache.hits/misses/injections/flushes/promotions             │
│  scouts.spawned/completed/timed_out/cache_hits              │
│  bus.messages_sent/signals_emitted                           │
│  token.consumed/estimated                                    │
│  agent.seconds_active/boots/crashes/recoveries               │
│  watchdog.timeouts/pets                                      │
│  icache.hits/misses/evictions                                │
│  tlb.hits/misses/flushes                                     │
│  interrupt.triggered.{nmi,high,normal,low}                   │
│  interrupt.handled.{nmi,high,normal,low}                     │
│                                                              │
│  Features: snapshot history ring buffer, delta/rate queries  │
│  PMU_SNAPSHOT_INTERVAL gated auto-snapshot                   │
│  Thread-safe (RLock)                                         │
│  Integrated: Watchdog, I-Cache, TLB, InterruptController     │
│  all increment via pmu.increment()                           │
└──────────────────────────────────────────────────────────────┘
```

### Watchdog Timer ✅

```
┌──────────────────────────────────────────────────────────────┐
│  Watchdog — CellWatchdog (src/l3/cell/components/cell_watchdog.py, 220L)     │
│                                                              │
│  Per-agent watchdog state machine:                           │
│  HEALTHY ──(missed pet)──> UNRESPONSIVE ──(timeout)──> CRASHED│
│     │                          │                             │
│     └── pet() resets           └── pet() recovers            │
│                                                              │
│  Background daemon thread polling at POLL_INTERVAL (5s)      │
│  Auto-pet on card completion in AgentTerminal                │
│  Callbacks: on_timeout, on_recovery, on_crash                │
│    on_crash → InterruptController NMI + MMU TLB flush       │
│  Increments PMU: watchdog.timeouts, watchdog.pets            │
└──────────────────────────────────────────────────────────────┘
```

### I-Cache (Instruction Cache) ✅

```
┌──────────────────────────────────────────────────────────────┐
│  I-Cache — ICache (src/l3/cell/components/cell_icache.py, 194L)              │
│                                                              │
│  Read-only cache for structural Cell knowledge:              │
│    - Tool definitions    (entry_type="tool")                 │
│    - Card templates      (entry_type="template")             │
│    - HTN methods         (entry_type="htn")                  │
│    - Constitution rules  (entry_type="constitution")         │
│    - Territory maps      (entry_type="territory")            │
│    - Agent config        (entry_type="config")               │
│                                                              │
│  LFU eviction (not TTL — frequency decays via decay factor)  │
│  Longer lifetime than D-Cache: ICACHE_TTL=1h default         │
│  Never flushes to MemoryManager (not episodic memory)        │
│  Search by entry_type or tag, sorted by frequency            │
│  Backs MMU page walk (territory maps loaded from I-Cache)    │
│  PMU tracks: icache.hits/misses/evictions                    │
└──────────────────────────────────────────────────────────────┘
```

### MMU + TLB ✅

```
┌──────────────────────────────────────────────────────────────┐
│  MMU+TLB — CellMmu + CellTlb (src/l3/cell/components/cell_mmu.py, 255L)     │
│                                                              │
│  Translates territory pattern → agent_id + ring clearance    │
│  Three-level translation cascade:                            │
│    1. TLB lookup (fast path, 64 entries max)                 │
│    2. Page walk: I-Cache "territory.*" lookup (medium path)  │
│    3. Fallback: agents dict scan (slow path)                 │
│                                                              │
│  TLB: LFU-like eviction (lowest hit_count evicted first)     │
│  TLB_FLUSH triggers:                                         │
│    - Agent removal  (flush_agent)                            │
│    - Territory reassignment (flush_territory)                 │
│    - Watchdog crash on_crash → TLB.flush_agent()             │
│    - InterruptController NMI → TLB.flush_all()               │
│  PMU tracks: tlb.hits/misses/flushes                         │
└──────────────────────────────────────────────────────────────┘
```

### InterruptController (Priority Interrupt) ✅

```
┌──────────────────────────────────────────────────────────────┐
│  InterruptController (src/l3/cell/components/cell_interrupt.py, 296L)        │
│                                                              │
│  4 priority levels:                                          │
│    NMI    (0) — unmaskable, fires inline                     │
│    HIGH   (1) — maskable                                     │
│    NORMAL (2) — maskable                                     │
│    LOW    (3) — maskable                                     │
│                                                              │
│  16 built-in IRQ slots (0-15):                               │
│    NMI:   watchdog.crash, constitution.violation,            │
│           cell.restart, security.breach                      │
│    HIGH:  task.complete, review.response,                    │
│           task.timeout, agent.crash                          │
│    NORMAL: task.assign, message.delivered,                   │
│           review.request, scout.done                         │
│    LOW:   heartbeat, scout.progress, cache.flush, token.usage│
│                                                              │
│  Non-NMI: queued per-priority, dispatch_pending() drains     │
│  NMI bypasses all masks and queues (inline execution)        │
│  PMU tracks: interrupt.triggered/handled.{priority}          │
└──────────────────────────────────────────────────────────────┘
```

### SubAgent Framework ✅

```
┌──────────────────────────────────────────────────────────────┐
│  SubAgent Framework (src/l3/agent/subagent*.py, 8 files, ~960L)   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ subagent_spec.py      — SubAgentSpec dataclass         │  │
│  │                         role/tool set/model/timeout    │  │
│  │                         post_actions (scout verify)    │  │
│  │                         8 built-in specs: security-    │  │
│  │                         auditor, code-reviewer,        │  │
│  │                         documenter, data-analyst,      │  │
│  │                         architect, helper, refactor-   │  │
│  │                         agent, fixer                   │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ subagent_task.py      — SubAgentTask instance           │  │
│  │                         Two execution modes:           │  │
│  │                         1. read_only=True →            │  │
│  │                            engine.generate (fast)       │  │
│  │                         2. read_only=False →           │  │
│  │                            AgentLoop.tool_use (multi)   │  │
│  │                         Post-action chain (auto-scout)  │  │
│  │                         Delivers via CellMessage        │  │
│  │                         SUBAGENT_RESULT to parent       │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ subagent_gate.py     — SubAgentGate card classifier     │  │
│  │                        Inspects card phases/tasks for   │  │
│  │                        write tools → 'explore'|'execute' │  │
│  │                        build_spec(card_type) → spec     │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ subagent_pool.py     — SubAgentPool async delegation    │  │
│  │                        Dual-buffer (explore/execute)    │  │
│  │                        ThreadPoolExecutor per buffer    │  │
│  │                        commission() → task.start()      │  │
│  │                        collect() / collect_all()        │  │
│  │                        Results via CellMessage mailbox  │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ subagent_dispatcher.py — @mention parsing + dispatch    │  │
│  │                         SubAgentDispatcher singleton   │  │
│  │                         parse_mentions("fix @arch")     │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ subagent_merger.py    — ResultMerger                    │  │
│  │                         Multi-agent merge + conflict    │  │
│  │                         detection (keyword-level)       │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ subagent.py           — Legacy inline SubAgent          │  │
│  │                         (sync, Ring 1, stateless)      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Orchestration (src/l3/services/cell_orchestrate.py):        │
│    SubAgentOrchestrator uses SubAgentPool instead of         │
│    old cell.subagent_dispatch() + manual polling.            │
│    Fork-join via _pool.commission() + collect_all().         │
│                                                              │
│  Tool Registry (src/l3/tool_system/tool_registry.py):        │
│    Rewritten from flat module globals to ToolRegistry class  │
│    backed by MapRegistry from l1.kernel.registry_base.       │
│    Mute/plugin/middleware state lives on instance.            │
│    Backward-compatible module-level functions preserved.      │
│                                                              │
│  REST API:                                                   │
│    POST /api/subagent/dispatch    — Dispatch subagent       │
│    GET  /api/subagent/:id/result  — Get subagent result     │
│    DELETE /api/subagent/:id       — Cancel subagent         │
│    GET  /api/subagent/specs       — List subagent specs     │
│    POST /api/subagent/spec        — Register subagent spec  │
│    POST /api/subagent/merge       — Merge results           │
└──────────────────────────────────────────────────────────────┘
```

### Cell Orchestration — core ✅ / ◐

```
┌──────────────────────────────────────────────────────────────┐
│  Cell Orchestration                                           │
│                                                              │
│  ├── cell/__init__.py (28 methods)            ✅ Complete         │
│  ├── cell_agent.py (agent registration)       ✅ Complete         │
│  ├── cell_buffer.py (CircularBuffer)         ✅ Complete         │
│  ├── cell_convention.py (convene)            ✅ Complete         │
│  ├── cell_decompose.py (decomposition)       ✅ Complete         │
│  ├── cell_monitor.py (health events)         ✅ Complete         │
│  ├── cell_types.py (data types)              ✅ Complete         │
│  ├── cell_token_merger.py (token tracking)    ✅ Complete         │
│  ├── cell_cache.py (L2 shared cache)         🔧 Uncommitted       │
│  └── cell_orchestrate.py (fork-join)         ✅ Complete         │
└──────────────────────────────────────────────────────────────┘
```

### L3A — Intent Parser ◐

```
┌──────────────────────────────────────────────────────────────┐
│  L3A — Intent Parser                                         │
│                                                              │
│  ├── process_intent(text) → Card              ✅ Basically usable    │
│  ├── User profiling / habit learning           ⬜ Not Started     │
│  ├── Intent correction loop (L3C feedback)     ⬜ Not Started     │
│  └── Multi-turn dialog context accumulation   ◐ Basic implementation    │
└──────────────────────────────────────────────────────────────┘
```

### L3C — Behavior Collector ⬜ (Design Phase)

```
┌──────────────────────────────────────────────────────────────┐
│  L3C — Behavior Collector (peer to L3A)                      │
│                                                              │
│  ├── Collect user correction patterns        ⬜ Not Started       │
│  ├── Collect intent→tool mapping preferences  ⬜ Not Started       │
│  ├── Collect command vs NLP switching patterns ⬜ Not Started       │
│  └── Feedback → L3A / L2 Shell                ⬜ Not Started       │
└──────────────────────────────────────────────────────────────┘
```

### Agent Terminal — core ✅

```
┌──────────────────────────────────────────────────────────────┐
│  AgentTerminal (src/l3/agent_terminal/)                       │
│                                                              │
│  ├── stdin/stdout/stderr three pipes          ✅              │
│  ├── Worker Thread Pool (_max_workers=4)      ✅              │
│  ├── boot() → IDLE → PROCESSING → CRASHED    ✅              │
│  ├── dispatch/wait_for_result                 ✅              │
│  ├── spawn_scout_async/collect_scout          ✅              │
│  ├── pause/resume/shutdown                    ✅              │
│  └── output_guard                             ✅              │
└──────────────────────────────────────────────────────────────┘
```

### AgentLoop ◐

```
┌──────────────────────────────────────────────────────────────┐
│  AgentLoop (src/l3/agent/agent_loop.py)                             │
│                                                              │
│  ├── LLM multi-turn tool_use()               ✅               │
│  ├── ToolLoopDetector                        ✅               │
│  ├── CoarseRepeatDetector                    ✅               │
│  ├── TodoTracker                             ✅               │
│  ├── VerifyCadence                           ✅               │
│  ├── LoopControl configurable                ✅ (Just completed)      │
│  └── Verifier (LLM self-check)               ◐ Basic implementation       │
└──────────────────────────────────────────────────────────────┘
```

### Memory System — core ✅ + CellCache 🔧

```
┌──────────────────────────────────────────────────────────────┐
│  Memory System                                                 │
│                                                              │
│  ├── MemoryManager 4-ring (R1-R4)           ✅                │
│  ├── MemEntry + cell_id partition            ✅                │
│  ├── Quality scoring + provenance            ✅                │
│  ├── FTS5 full-text search (R3)              ✅                │
│  ├── R4Agent Archive + skill evolution       ✅                │
│  ├── forget_cell() / forget_agent()          ✅                │
│  ├── CellCache (3-tier L2)                   🔧 Uncommitted         │
│  └── Memory → AgentLoop bridge               ✅                │
└──────────────────────────────────────────────────────────────┘
```

### Card System ✅

```
┌──────────────────────────────────────────────────────────────┐
│  Card System (l3/card/)                                    │
│                                                              │
│  ├── CardUnified + phases + steps            ✅               │
│  ├── CardRegistry (queue + dispatcher)       ✅               │
│  ├── CardBuilder (intent → Card)             ✅               │
│  ├── CardGate (small/medium/large/disputed)  ✅               │
│  ├── CardPool (remote registry + sync)       ✅               │
│  ├── CardState (backward compat)             ✅               │
│  ├── CardYaml (YAML loader)                  ✅               │
│  └── card_registry_protocol (net)            ✅               │
└──────────────────────────────────────────────────────────────┘
```

### HTN Decomposition — core ✅ + A/B 🔧

```
┌──────────────────────────────────────────────────────────────┐
│  HTN Decomposition                                             │
│                                                              │
│  ├── HTN-C (Intra-cell execution decomposition)  ✅                │
│  ├── HTN-A (Global intent sharding)             🔧 Uncommitted         │
│  ├── HTN-B (Inter-cell routing decomposition)   🔧 Uncommitted         │
│  └── Decomposer (General Assembly pipeline)     ✅               │
└──────────────────────────────────────────────────────────────┘
```

### L3B — Cross-Cell Routing ◐

```
┌──────────────────────────────────────────────────────────────┐
│  L3B — Cross-Cell Coordination                                 │
│                                                              │
│  ├── L3B (legacy route/resolve)              ✅                │
│  ├── L3BComposite (HTN-B + routing)          🔧 Uncommitted         │
│  ├── L3B Bus (5 message types)               🔧 Uncommitted         │
│  └── L3B Message Pool (Hot Ring + SQLite)    🔧 Uncommitted         │
└──────────────────────────────────────────────────────────────┘
```

### Scheduler ✅

```
│  ├── scheduler.py (unified)                  ✅                │
│  ├── scheduler_rate.py (rate limits)         ✅                │
│  ├── scheduler_scope.py (scope-based)        ✅                │
│  ├── scheduler_time.py (time-slice)          ✅                │
│  ├── scheduler_router.py (intent routing)    ✅                │
│  └── scheduler_types.py (dataclasses)        ✅                │
```

### Pipeline / Tools ✅

```
│  ├── tool_pipeline.py (9-step)               ✅                │
│  ├── tool_spec.py (spec + ring)              ✅                │
│  ├── tool_registry.py (ToolRegistry class)   🔧                │
│  ├── tool_config.py (YAML tool config)       ✅                │
│  ├── tool_policy.py (5-layer visibility)     ✅                │
│  ├── tool_mode.py (global read/write)        ✅                │
│  └── tools/ (35+ tool handlers)              ✅                │
```

### Execution ✅

```
│  ├── execution_engine.py                     ✅                │
│  ├── execution_plan.py (Card→Plan)           ✅                │
│  └── execution_verify.py                     ✅                │
```

### Buses & Monitoring ✅

```
│  ├── monitor_bus.py (JSONL + SSE)            ✅                │
│  ├── observability_bus.py (alert/metric)     ✅                │
│  ├── error_bus/ (3-tier + dedup)             ✅                │
│  ├── log.py (rotation + bridging)            ✅                │
│  ├── reference_channel.py (async recorder)   ✅                │
│  ├── stats_center.py (metric aggregation)    ✅                │
│  ├── message_gate.py (policy engine)         ✅                │
│  └── counter.py (token/tool/loop)            ✅                │
```

### Queue / Approval ✅

```
│  ├── pending_queue.py (human approval)       ✅                │
│  ├── approval_gate.py (danger threshold)     ✅                │
│  ├── card_gate.py (card classification)      ✅                │
│  └── card_pool.py (remote registry)          ✅                │
```

### Security ✅

```
│  ├── central_security.py (6-gate)            ✅                │
│  ├── content_trust.py (provenance)           ✅                │
│  └── tool_policy.py (visibility)            ✅                │
```

### Config / Settings ✅

```
│  ├── config_loader.py (yaml load)            ✅                │
│  ├── config_handlers.py (22 handlers)        ✅ (Just +loop)     │
│  ├── settings_center.py (3-layer)            ✅ (Just +loop)     │
│  └── settings_adapter.py                     ✅                │
```

### Various ✅

```
│  ├── boot.py (5-step bootstrap)              ✅                │
│  ├── boot_init.py / bootstrap.py             ✅                │
│  ├── context.py / context_pool.py            ✅                │
│  ├── scout.py (scout pool)                   ✅                │
│  ├── think_registry.py (think quota)         ✅                │
│  ├── convergence.py (convention→card)        ✅                │
│  ├── convention.py (multi-agent meeting)     ✅                │
│  ├── statecharts.py (5-region state)         ✅                │
│  ├── fault_tolerance.py (checkpoint)         ✅                │
│  ├── verifier.py / verify_cadence.py         ✅                │
│  ├── stagno/detectors (loop detection)       ✅                │
│  ├── r4_agent.py (archive + skills)          ✅                │
│  ├── record_center.py (unified record facade) ✅               │
│  ├── cell_pmu.py (28 counters)               ✅                │
│  ├── cell_watchdog.py (per-agent timer)      ✅                │
│  ├── cell_icache.py (LFU instruction cache)   ✅                │
│  ├── cell_mmu.py (MMU + TLB)                 ✅                │
│  ├── cell_interrupt.py (priority IRQ)         ✅                │
│  ├── cell_orchestrate.py (fork-join via pool) ✅                │
│  ├── subagent*.py (8 files, framework)       ✅                │
│  ├── subagent_gate.py (explore/execute gate) 🔧                │
│  ├── subagent_pool.py (async delegation pool) 🔧                │
│  ├── identity.py (Ed25519 keys)              ✅                │
│  ├── wiring.py (port→adapter assembly)       ✅                │
│  ├── acb.py (Agent Control Block)            ✅                │
│  ├── package_manager.py (apt/pip/npm)        ✅                │
│  ├── 13 more files...                        ✅                │
```

### Discussion & Convergence 🔧

```
│  src/l3/discussion/                                              │
│  ├── issue_orchestrator.py (IssueCard→discussion session)   🔧   │
│  ├── answer_session.py (5-phase answer protocol)             🔧   │
│  ├── cell_answer_repo.py (per-Cell answer + checkpoint)      🔧   │
│  ├── answer_aggregator.py (cross-Cell merge/dedup)           🔧   │
│  ├── supplement_manager.py (classify supplements)            🔧   │
│  └── report_service.py (report→MD + L3A + SSE)               🔧   │
│                                                                   │
│  Bus events:                                                      │
│  ├── Cell listens: "discussion.start" → AnswerSession             │
│  ├── Cell emits:  "discussion.cell_complete" → orchestrator       │
│  ├── boot.py: blank constitution → auto-creates IssueCard         │
│  └── cell_execute.py: checks IssueOrchestrator for sessions       │
```

**Status: 🔧 Uncommitted (written + committed, full integration pending).**
- `AnswerSession`: 5 phases (independent answer → cross-examine → supplement → converge → report)
- `IssueOrchestrator`: session lifecycle, cell registration, cell_complete routing
- `AnswerAggregator`: cross-Cell answer merge with divergence detection
- Boot auto-trigger: blank `.nomos-rules.md` creates IssueCard for territorial discussion

## L4 Bridge — 45 files, 9,141 lines ✅

```
│  ├── api_gateway.py (HTTP + Middleware)      ✅                │
│  ├── api_handlers/ (mixed-in, 35 categories) ✅                │
│  ├── api_handlers_agent.py (Agent Config API)✅                │
│  ├── api_routes.py (153 routes)              ✅                │
│  ├── api_middleware.py (CORS/Locale/Body)    ✅                │
│  ├── llm.py / llm_base / llm_providers       ✅                │
│  ├── llm_worker/ (RPC worker)                ✅                │
│  ├── sandbox/ (COW isolation + structured diff)       ✅                │
│  ├── mcp_bridge.py (MCP adapter)             ✅                │
│  ├── rpc/ (protocol + transport)             ✅                │
│  ├── supervisor.py (process supervisor)      ✅                │
│  ├── adapters/ (6 port implementations)       ✅                │
│  ├── credential_vault.py (AES-256)           ✅                │
│  ├── sse_bridge.py (streaming)               ✅                │
│  ├── search_engine.py (full-text)            ✅                │
│  ├── cron_scheduler.py                       ✅                │
│  └── 10 more files...                        ✅                │
```

## L5 User — 2 files, 472 lines ✅

```
│  ├── cli.py (Typer CLI, boot/status/exec)   ✅                │
│  └── agent_runtime.py (execution loop)       ✅                │
```

## Not Yet Started (⬜)

```
│  L3A: User profiling / habit learning             ⬜                │
│  L3C: Behavior Collector                          ⬜                │
│  Heavy Desktop (Electron/Tauri)                   ⬜                │
│  Lightweight Desktop (chat + diff)                ⬜                │
│  VSCode Extension                                 ⬜                │
│  Multi-cluster / Distributed                      ⬜                │
│  License/Authorization system                     ⬜                │
```

## Summary

```
Layer       Files    Lines    Status
─────────────────────────────────────────
L1 Kernel    37     8,497    ✅ Complete
L2 Shell     10     1,977    ✅ Complete
L3 Cell     154    32,794    ✅ Core + PMU/Watchdog/ICache/MMU/IRQ/SubAgent + ◐ A/B/L3B + 🔧 CellCache
L4 Bridge    45     9,141    ✅ Complete
L5 User       2       472    ✅ Complete
tests        95    15,541    ✅ Core pass (94/94)
config        3       865    ✅ Complete
─────────────────────────────────────────
Total       346    69,101

Completed:        ~90% (L1/L2/L4/L5 + L3 core)
Partial:          ~5%  (L3A intent, HTN-A/B, L3B composites)
Uncommitted:      ~3%  (CellCache, HTN-A/B, L3B Bus/Pool, path fixes)
Not started:      ~2%  (L3C, Desktops, VSCode, License)
```

---

## Appendix: Internal Architecture Diagrams & Details

### A. Cell Internal Architecture Detailed Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         CELL (src/l3/cell/__init__.py, ~1070L)                   │
│                     cell_id / territory / RLock / emergency_flag                 │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  1. AGENT REGISTRY (dict[str, AgentInfo])                                  │   │
│  │     ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐  │   │
│  │     │ peer-0   │ peer-1   │ peer-2   │ governor │ architect│ ...peer  │  │   │
│  │     │ ring=3   │ ring=3   │ ring=3   │ ring=3   │ ring=2   │ ring=3   │  │   │
│  │     │ scouts=3 │ scouts=3 │ scouts=3 │ scouts=1 │ scouts=2 │ scouts=N │  │   │
│  │     │ full tls │ full tls │ full tls │          │          │          │  │   │
│  │     └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────┐                               │
│  │  2. Mailbox (dict[str, list[CellMessage]])    │ ─── 13 MessageTypes           │
│  │     max=CELL_MAILBOX_MAX_PER_AGENT(100)       │ TASK_HANDOFF / SCOUT_RESULT  │
│  │     TTL=CELL_MAILBOX_TTL(3600s)               │ CONSULT / VOTE_REQ/RESP      │
│  │                                                │ CROSS_REVIEW_REQ/RESP        │
│  │     ┌────────────────────────────────────┐    │ ESCALATE / CONVENE / REBUT   │
│  │     │ AgentA │ AgentB │ AgentC │ AgentD  │    │ PROPOSE_ISSUE / CONVENE_CLOSE│
│  │     │ Queue  │ Queue  │ Queue  │ Queue   │    │ CROSS_EXAMINE               │
│  │     └────────────────────────────────────┘    │ SUBAGENT_RESULT             │
│  └──────────────────────────────────────────────┘                               │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  3. CellCache — L2 Shared Cache (src/l3/cell/components/cell_cache.py, ~383L)             │   │
│  │                                                                          │   │
│  │     ┌── Hot Ring (50 slots, TTL=300s) ──────────────────────────────────┐  │   │
│  │     │  inject(key, value, summary, agent_id, entry_type, ttl)        │  │   │
│  │     │  lookup(key) → CellCacheEntry ← shared by all Agents in same Cell │  │   │
│  │     └────────────────────────────────────────────────────────────────┘  │   │
│  │     ┌── Index Chain (200 slots, TTL=15min) ────────────────────────────┐  │   │
│  │     │  IndexEntry{key, summary, agent_id, entry_type, importance}    │  │   │
│  │     │  Index survives after value is demoted to L3/R4                │  │   │
│  │     └────────────────────────────────────────────────────────────────┘  │   │
│  │     ┌── KV Cache (100 slots, TTL=30min, LRU) ──────────────────────────┐  │   │
│  │     │  Full value cache, swaps in from MemoryManager on miss          │  │   │
│  │     └────────────────────────────────────────────────────────────────┘  │   │
│  │     promote(key) → demoted value floats back to Hot Ring                │   │
│  │     flush() → dirty values written back to MemoryManager R2             │   │
│  │     search(query, limit) → cross-ring IndexEntry matching               │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  4. Circular Buffer (src/l3/cell/components/cell_buffer.py: CircularBuffer, ~64L)         │   │
│  │     ┌─ Rollback Ring (20 slots) ────────────────────────────────────────┐  │   │
│  │     │  pre-execution file snapshot (shutil.copy2 → tempfile)          │  │   │
│  │     │  on_evict → _archive_item("rollback", item) → R4 archive        │  │   │
│  │     │  Restored by rollback_card(card_id)                              │  │   │
│  │     └────────────────────────────────────────────────────────────────┘  │   │
│  │     ┌─ Card History Ring (100 slots) ───────────────────────────────────┐  │   │
│  │     │  {card_id, intent, completed_at, success}                       │  │   │
│  │     │  on_evict → _archive_item("card_history", item) → R4 archive    │  │   │
│  │     └────────────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  5. Card Execution Pipeline                                              │   │
│  │                                                                          │   │
│  │  Raw intent ──→ _raw_to_card() ──→ decompose_card() ──→ ExecutionPlan    │   │
│  │                      │ HTN / CardBuilder     │ territory-scoped          │   │
│  │                      └──────────┬────────────┘ sub-cards                 │   │
│  │                                 ▼                                        │   │
│  │  dispatch_card(target, action, target, params)                           │   │
│  │    1. Create TerminalCard → term.dispatch(card_id)                       │   │
│  │    2. emit_signal(EVENT_TASK_ASSIGN)                                     │   │
│  │    3. If write operation: _auto_cross_review() blocks and waits          │   │
│  │       → Send CROSS_REVIEW_REQ to all peer Agents                         │   │
│  │       → Wait for CROSS_REVIEW_RESP or timeout (60s)                      │   │
│  │       → Any peer veto causes rejection                                   │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  6. Lifecycle Hooks (Vetoable Interception Points)                        │   │
│  │     on_boot(agent_id)      — Observe (non-vetoable)                      │   │
│  │     on_shutdown()           — Observe (non-vetoable)                     │   │
│  │     on_spawn(id,role,terr) — Vetoable ({success:False})                  │   │
│  │     on_kill(id)             — Vetoable ({success:False})                 │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  7. Voting Protocol (src/l3/cell/components/cell_convention.py + src/l3/card/convention.py)           │   │
│  │     IssueCard → convene() → ConventionProtocol (Multi-Agent Deliberation) │   │
│  │       → convergence.py: converge() + to_execution_card()                  │   │
│  │       → Submit to CardRegistry → Standard Execution                       │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  8. Snapshot / Rollback                                                   │   │
│  │     _take_snapshot(card) → tempfile copy per step.target                  │   │
│  │     rollback_card(card_id) → 6 steps: checkpoint→files→sandbox→terminal   │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  9. PMU — Performance Monitoring Unit (src/l3/cell/components/cell_pmu.py, ~236L)         │   │
│  │     28 hardware-style 64-bit counters: cards/tools/cache/scouts/           │   │
│  │     bus/token/agent/watchdog/icache/tlb/interrupt groups                  │   │
│  │     Snapshot history ring buffer, delta/rate queries                      │   │
│  │     All other HW units call pmu.increment() on significant events        │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  10. Watchdog Timer (src/l3/cell/components/cell_watchdog.py, ~220L)                      │   │
│  │      Per-agent state machine: HEALTHY → UNRESPONSIVE → CRASHED            │   │
│  │      Background daemon thread, poll at POLL_INTERVAL                      │   │
│  │      Auto-pet on card completion via AgentTerminal                        │   │
│  │      on_crash → InterruptController.trigger(NMI, "watchdog.crash")       │   │
│  │               + MMU.flush_agent(dead)                                     │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  11. I-Cache — Instruction Cache (src/l3/cell/components/cell_icache.py, ~194L)           │   │
│  │      Read-only LFU cache: tools/templates/HTN/constitution/territory     │   │
│  │      ICACHE_TTL=1h default, frequency decay to age stale entries         │   │
│  │      Backs MMU page walk (territory.* keys)                               │   │
│  │      Search by entry_type or tag, sorted by frequency                     │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  12. MMU + TLB — Memory Management Unit (src/l3/cell/components/cell_mmu.py, ~255L)       │   │
│  │      territory_pattern → agent_id translation authority                    │   │
│  │      TLB (64 entries max): LFU-like eviction (lowest hit_count)           │   │
│  │      Translation cascade: TLB → I-Cache page walk → agents dict scan     │   │
│  │      Flush on: agent removal, territory reassignment, watchdog crash      │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  13. InterruptController (src/l3/cell/components/cell_interrupt.py, ~296L)                │   │
│  │      4 priority levels: NMI(0/unmaskable) / HIGH(1) / NORMAL(2) / LOW(3) │   │
│  │      16 built-in IRQ slots (0-15): watchdog.crash, constitution.violation│   │
│  │      task.complete, review.response, message.delivered, heartbeat, etc.  │   │
│  │      NMI fires inline; other priorities queue → dispatch_pending()       │   │
│  │      Wraps EventBus — legacy emit() routes through default NORMAL pri    │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### B. AgentTerminal Internal Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AGENT TERMINAL (src/l3/agent_terminal/, ~640L)            │
│                    Singleton: get_terminal(agent_id, role, territory)        │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │  stdin       │  │  stdout      │  │  stderr      │  │  file_cache      │ │
│  │  deque[Term  │  │  deque[Card  │  │  deque[str]  │  │  IsolatedCache   │ │
│  │  inalCard]   │  │  Result]     │  │  max=200     │  │  (per-cell_id)   │ │
│  │  max=200     │  │  max=500     │  │              │  │                  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘  └──────────────────┘ │
│         │                │                                                   │
│         ▼                ▼                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Worker Thread Pool (max=TERMINAL_MAX_WORKERS=4)                     │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐      │   │
│  │  │ worker-0   │ │ worker-1   │ │ worker-2   │ │ worker-3     │      │   │
│  │  │ _process   │ │ _process   │ │ _process   │ │ _process     │      │   │
│  │  │  _card()   │ │  _card()   │ │  _card()   │ │  _card()     │      │   │
│  │  └──────┬─────┘ └──────┬─────┘ └──────┬─────┘ └──────┬───────┘      │   │
│  └─────────┼──────────────┼──────────────┼──────────────┼──────────────┘   │
│            ▼              ▼              ▼              ▼                  │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  AgentLoop (l3/agent/agent_loop.py) — LLM multi-turn tool_use()            │   │
│  │                                                                       │   │
│  │  ┌─────────────────────────────────────────────────────────────┐     │   │
│  │  │  run(max_steps=10, timeout=120s)                             │     │   │
│  │  │                                                              │     │   │
│  │  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐ │     │   │
│  │  │  │ LLM Engine   │──→│ Tool Pipeline │──→│ Memory Store    │ │     │   │
│  │  │  │ (l4.llm)     │   │ (9-step exec) │   │ (ring 1 auto)   │ │     │   │
│  │  │  └──────────────┘   └──────────────┘   └──────────────────┘ │     │   │
│  │  │                                                              │     │   │
│  │  │  Self-Correction Mechanisms:                                  │     │   │
│  │  │    ToolLoopDetector — SHA256(tool+args+result) ×3→WARN ×4→STOP│   │   │
│  │  │    CoarseRepeatDetector — same tool name ×3→NUDGE ×6→STOP    │     │   │
│  │  │    TodoTracker — Persistent State Machine                     │     │   │
│  │  │    VerifyCadence — write/edit → nudge build/check            │     │   │
│  │  └─────────────────────────────────────────────────────────────┘     │   │
│  │                                                                       │   │
│  │  Input: TerminalCard → _execute_card() → LLM tool_use()              │   │
│  │  Output: CardResult {card_id, action, success, output, findings}     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Lifecycle States:                                                            │
│    BOOTING ──→ IDLE ──→ PROCESSING ──→ CRASHED                               │
│                     │           │                                            │
│                     ├──→ BLOCKED│                                            │
│                     │           └──→ STOPPED                                 │
│                     └──────────────→ STOPPED                                 │
│                                                                              │
│  Mode: assembly (default) / direct                                           │
│  Helpers: ScoutPool (shared, Ring 1 read-only) / SubAgent (full AgentLoop)  │
│  Cross-Agent Messages: add_todo / list_todos / cancel_todo / todo_stats     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### C. Tool Pipeline — 9-Step Instruction Execution

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     TOOL PIPELINE (src/l3/tool_system/tool_pipeline.py, ~295L)           │
│                                                                               │
│  Tool Call                                                                    │
│     │                                                                         │
│     ▼  ┌──────────────────────────────────────┐                              │
│  1.    │ Clearance Check: agent.ring >= tool   │  BLOCK if ring too low       │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  2.    ┌──────────────────────────────────────┐                              │
│        │ Rate Limit: calls/min per ring        │  Ring1=60 R2.5=20 R3=5     │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  3.    ┌──────────────────────────────────────┐                              │
│        │ Constitution: is_allowed(action,      │  BLOCK if violation         │
│        │ agent_id, target)                     │                              │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  3b.   ┌──────────────────────────────────────┐                              │
│        │ GateChain G1-G5                       │                              │
│        │  G1: tool whitelist                   │                              │
│        │  G2: identity + Ed25519 keypair       │                              │
│        │  G3: territory + risk score           │                              │
│        │  G4: escalation (danger >= 4)         │                              │
│        │  G5: composite (reputation × danger   │                              │
│        │       × history × frequency)          │                              │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  4.    ┌──────────────────────────────────────┐                              │
│        │ Allocator: alloc(tokens) from budget  │  BLOCK if quota exhausted   │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  5.    ┌──────────────────────────────────────┐                              │
│        │ Request Pool: reputation-weighted     │  Ring 3: witness approval   │
│        │ scheduling for Ring 2.5               │                              │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  6.    ┌──────────────────────────────────────┐                              │
│        │ File Lock: rwlock.write_lock() /path  │  timeout=30s deadlock       │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  7.    ┌──────────────────────────────────────┐                              │
│        │ Execute: ToolSpec.handler()           │  sandbox COW if write       │
│        │                                       │  timeout=60s                │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  8.    ┌──────────────────────────────────────┐                              │
│        │ Memory Store: auto-remember result    │  Ring 1 via MemoryManager   │
│        └──────────┬───────────────────────────┘                              │
│                  ▼                                                           │
│  9.    ┌──────────────────────────────────────┐                              │
│        │ Release: unlock → free alloc → audit  │                              │
│        └──────────────────────────────────────┘                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### D. Memory Hierarchy

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                  Memory Hierarchy (4-Level Pyramid)                           │
│                                                                              │
│  Level  Name        Capacity   Slots  TTL      Backend     Eviction Policy  │
│  ────  ────       ──────     ──── ─────   ──────     ────────               │
│  L0    ContextReg  4K tokens  200    ∞      ContextPool LRU                  │
│  L1    Working     8K tokens   32  30min    deque       token pressure       │
│  L2    Short-Term 32K tokens  200   24h     JSONL file  age/FIFO            │
│  L3    Long-Term 128K tokens 1000    ∞      SQLite+FTS5 never→archive       │
│  L4    Archive      ∞          ∞     ∞      Disk dir    R4Agent lifecycle   │
│                                             fonds/series                     │
│  L2    CellCache   Hot/Idx/KV  50/200/100  per-tier    CellCache.evict      │
│        (Intra-Cell)            slots       TTL                                 │
│                                                                              │
│  Data Flow:                                                                   │
│    AgentLoop ← L0 Register ← L1 Working ← L2 Short-Term ← L3 Long-Term      │
│                                    │                        │               │
│                                    │ pressure ≥80%          │ importance    │
│                                    ▼                        │ ≥0.7          │
│                              Swapper: swap_out              ▼               │
│                              R1 → R2/R3               R4Agent: archive      │
│                                                        → fonds/series        │
│                                                                              │
│  Startup Recovery:                                                            │
│    R4 → ring3_from_archive() → R3 (archive_orchestrator.py)                 │
│    R3/R2 → restore() → MemoryManager (memory.py, JSONL+SQLite)              │
│                                                                              │
│  Cell L2 Cache (fast layer between AgentTerminal and MemoryManager):        │
│    AgentTerminal ↔ CellCache (hot/index/kv) ↔ MemoryManager R1/R2           │
│                                                   ↕                          │
│                                              Swapper / PagerBridge          │
│                                                   ↕                          │
│                                              R3 SQLite / R4 Archive         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### E. Bus Architecture — On-Chip Interconnect

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                   7 Message Buses (On-Chip Interconnect)                      │
│                                                                              │
│  1. EventBus      (l1/kernel/event.py, 161L)  — Kernel Publish/Subscribe    │
│     Signal(TASK_ASSIGN|CANCEL|REVIEW|TOKEN_USAGE|AGENT_BOOT|ARCHIVE_ALERT)  │
│     emit_signal() / subscribe() / SignalType enum                           │
│     → CentralCollector, L3A, Cell                                           │
│                                                                              │
│  2. MonitorBus    (l3/bus/monitor_bus.py, 220L)  — Unified Monitoring           │
│     MonitorEvent(type, source, severity, cell_id, data)                     │
│     JSONL Persistence + SSE Stream + Query API                              │
│                                                                              │
│  3. ErrorBus      (l3/error_bus/, 725L)  — ~190 Capture Points              │
│     capture("msg", exc=e) / error_boundary("ctx")                           │
│     SHA-256 Dedup / LogService + EventBus + SSE                             │
│                                                                              │
│  4. LogService    (l3/bus/log.py, 288L)  — System Log                           │
│     log.info() / install_handler() → Rotating JSON File                     │
│                                                                              │
│  5. ReferenceCh.  (l3/bus/reference_channel.py, 260L)  — Async Audit Trail      │
│     record("event", data) → JSONL Buffer → flush(5s or 100 events)          │
│                                                                              │
│  6. Observability (l3/bus/observability_bus.py, 143L)  — Alerts/Health/Metrics  │
│     observe(kind, source, data) → MonitorBus → SSE → UI                     │
│                                                                              │
│  7. MessageGate   (l3/bus/message_gate.py, 169L)  — Policy Engine Filter        │
│     allow/block/mute/hold/redirect rules, dependency-aware                   │
│                                                                              │
│  SSE Bridge (l4/sse_bridge.py, 132L):                                       │
│    GET /api/events → Server-Sent Events Stream                              │
│    Subscribe MonitorBus + ErrorBus + StatsCenter → JSON Frame              │
│                                                                              │
│  Port Interfaces (l1/kernel/ports.py, 335L, 7 Ports):                        │
│    TransportPort / ChannelPort / EventBusPort / WorkerPort                  │
│    I18nPort / CardRegistryPort / MonitorBusPort                             │
│    7 adapters in l4/adapters/ — Hexagonal Architecture                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

### F. 12 Coprocessors (Central Control Systems)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       12 Coprocessors                                         │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │  1. CentralController  (l3/cell/peers/l3.py, 224L)  — Intent Lifecycle Controller   │ │
│ │     process_intent("fix login bug") → Card → CardRegistry → Execution    │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  2. CentralScheduler   (l3/scheduler/scheduler*.py, 6 files)  — 5-Dimensional Scheduling│ │
│ │     Rate / Time Slice / Scope / Routing / Priority Queue                 │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  3. R4Agent            (l3/memory/r4_agent.py, 443L)  — Archive + Skill Evolution  │ │
│ │     archive_ring3 / restore_ring3 / get_lean_cases / evolve_skill        │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  4. CellMonitor        (l3/cell/components/cell_monitor.py, 209L)  — Per-Cell Health Monitor │ │
│ │     record / get_events / stats — Send MonitorEvent to MonitorBus        │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  5. CentralSecurity    (l3/services/central_security.py, 166L)  — 6-Gate Unified Check│ │
│ │     check_all(action, agent, target, tool) → {allowed, gates}            │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  6. CentralMemory      (l3/memory/central_memory.py, 169L)  — R1-R4 Coordinator    │ │
│ │     remember / recall / compact / archive_ring3 / stats                  │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  7. CentralPlugin      (l3/services/central_plugin.py, 152L)  — Plugin Lifecycle     │ │
│ │     install_tool_plugin / remove_tool_plugin / install_mcp / list        │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  8. CentralCollector   (l3/cell/peers/central_collector.py, 149L)  — Token Aggregation │ │
│ │     cell_total / global_quota / stats  — TOKEN_CELL_QUOTA=5M             │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │  9. L3B                (l3/bus/l3b.py, 81L)  — Cross-Cell Routing            │ │
│ │     route(card_id, target_cell) → Dispatch to another Cell               │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │ 10. InterruptController (cell_interrupt.py, 296L)  — Priority IRQ Ctrl   │ │
│ │     4 pri levels: NMI/HIGH/NORMAL/LOW, 16 IRQ slots, 2 NMI sources      │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │ 11. CentralMemory      → Same as #6 (R1-R4 Coordinator)                 │ │
│ │     (counted separately as R4Agent + CentralMemory are both archivers)   │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │ 12. StatsCenter       (stats_center.py, 341L)  — Cross-Cell Metric Agg  │ │
│ │     ingest / query / top / SSE / PMU snapshot + CentralCollector srcs    │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### G. L2 Shell Command Dispatch Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  Shell Command Dispatch (l2/l2_shell/__init__.py: dispatch())        │
│                                                                      │
│  text ──→ "|" in text? ──→ YES → _pipeline(segments)                │
│             │                                                       │
│             NO                                                      │
│             ▼                                                       │
│        starts with "/"? ──→ YES → shlex.split → get_command(cmd)    │
│             │                       → get_handler(cmd)(args)        │
│             NO                                                      │
│             ▼                                                       │
│        ShellState.is_direct()? ──→ YES → send_direct_message()      │
│             │                       → guard_output()                 │
│             NO                                                      │
│             ▼                                                       │
│        _l3a_intent(text) → coord.process_intent()                   │
└──────────────────────────────────────────────────────────────────────┘

  Pipeline Mechanism:
    cmd1 args | cmd2 args   →   Segmented execution, prev result injected via {key} into next params
    Supports three modes: Map/Chain/Passthrough
    aggregated = {}  # per-agent aggregated result
```

### H. Four-Layer Security Architecture

```
┌────────────────────────────────────────────────────────────┐
│                   Four-Layer Security Architecture           │
│                                                             │
│  Outer Ring: Constitution (constitution.py)                 │
│    .nomos-rules.md → 14+ built-in rules, highest authority  │
│     §4.7: No Agent may modify the Constitution              │
│                                                             │
│  Middle Ring: GateChain G1-G5 (gatechain.py)               │
│    Non-bypassable tool authorization pipeline, Ledger records risk analysis │
│                                                             │
│  Inner Ring: Tool Pipeline (tool_pipeline.py)               │
│    9 steps: clearance → rate → constitution → gatechain     │
│         → alloc → pool → lock → execute → release          │
│                                                             │
│  Isolation Layer: Sandbox (l4/sandbox/cell_sandbox.py)                   │
│    Copy-on-Write, 5 config files (DANGER_0 ~ DANGER_4)     │
│     Write to sandbox + compute hunks → L3 approval → flush back to project file            │
│                                                             │
│  Layer Import Constraints (test_layer_imports.py):          │
│    L5 → L4/L3/L2/L1  ✅                                    │
│    L4 → L3/L2/L1       ✅ (16 whitelist entries)           │
│    L3 → L2/L1          ✅ (3 whitelist entries)            │
│    L2 → L1             ✅                                    │
│    L1 → Any upper layer   ❌ Forbidden                      │
└────────────────────────────────────────────────────────────┘
```
