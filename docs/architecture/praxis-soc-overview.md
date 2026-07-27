# Praxis Agent OS — System-on-Chip Overview

> **Status map:** ✅ 完成 / ◐ 部分完成 / ⬜ 未开始 / 🔧 工作区未提交

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

**Status: ✅ 全部完成。** L1 是打磨最多的层，没有已知缺口。

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

**Status: ✅ 全部完成。** 39 条命令 + pipeline + scope 解析 + i18n。

## L3 Cell — 148 files, 31,293 lines

### L3A — Intent Parser ◐

```
┌──────────────────────────────────────────────────────────────┐
│  L3A — Intent Parser                                         │
│                                                              │
│  ├── process_intent(text) → Card              ✅ 基本可用    │
│  ├── 用户画像 / 习惯学习                       ⬜ 未开始     │
│  ├── 意图纠正回路 (L3C 反馈)                    ⬜ 未开始     │
│  └── 多轮对话上下文积累                        ◐ 基础实现    │
└──────────────────────────────────────────────────────────────┘
```

### L3C — Behavior Collector ⬜（设计阶段）

```
┌──────────────────────────────────────────────────────────────┐
│  L3C — Behavior Collector (与 L3A 同级)                      │
│                                                              │
│  ├── 采集用户纠正模式                        ⬜ 未开始       │
│  ├── 采集意图→工具映射偏好                    ⬜ 未开始       │
│  ├── 采集命令 vs NLP 切换模式                 ⬜ 未开始       │
│  └── 反馈 → L3A / L2 Shell                    ⬜ 未开始       │
└──────────────────────────────────────────────────────────────┘
```

### Cell Orchestration — core ✅ / ◐

```
┌──────────────────────────────────────────────────────────────┐
│  Cell Orchestration                                           │
│                                                              │
│  ├── cell/__init__.py (28 方法)              ✅ 完成         │
│  ├── cell_agent.py (agent 注册)              ✅ 完成         │
│  ├── cell_buffer.py (CircularBuffer)         ✅ 完成         │
│  ├── cell_convention.py (convene)            ✅ 完成         │
│  ├── cell_decompose.py (分解)                ✅ 完成         │
│  ├── cell_monitor.py (健康事件)              ✅ 完成         │
│  ├── cell_types.py (数据类型)                ✅ 完成         │
│  ├── cell_token_merger.py (token 跟踪)       ✅ 完成         │
│  └── cell_cache.py (L2 共享缓存)             🔧 未提交       │
└──────────────────────────────────────────────────────────────┘
```

### Agent Terminal — core ✅

```
┌──────────────────────────────────────────────────────────────┐
│  AgentTerminal (src/l3/agent_terminal/)                       │
│                                                              │
│  ├── stdin/stdout/stderr 三管道               ✅              │
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
│  AgentLoop (src/l3/agent_loop.py)                             │
│                                                              │
│  ├── LLM multi-turn tool_use()               ✅               │
│  ├── ToolLoopDetector                        ✅               │
│  ├── CoarseRepeatDetector                    ✅               │
│  ├── TodoTracker                             ✅               │
│  ├── VerifyCadence                           ✅               │
│  ├── LoopControl 可配置化                     ✅ (刚完成)      │
│  └── Verifier (LLM self-check)               ◐ 基础实现       │
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
│  ├── CellCache (3-tier L2)                   🔧 未提交         │
│  └── Memory → AgentLoop bridge               ✅                │
└──────────────────────────────────────────────────────────────┘
```

### Card System ✅

```
┌──────────────────────────────────────────────────────────────┐
│  Card System (l3/card*.py)                                    │
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
│  ├── HTN-C (Cell 内执行分解)                 ✅                │
│  ├── HTN-A (全局意图分片)                    🔧 未提交         │
│  ├── HTN-B (Cell 间路由分解)                 🔧 未提交         │
│  └── Decomposer (General Assembly pipeline)   ✅               │
└──────────────────────────────────────────────────────────────┘
```

### L3B — Cross-Cell Routing ◐

```
┌──────────────────────────────────────────────────────────────┐
│  L3B — Cross-Cell Coordination                                 │
│                                                              │
│  ├── L3B (legacy route/resolve)              ✅                │
│  ├── L3BComposite (HTN-B + routing)          🔧 未提交         │
│  ├── L3B Bus (5 message types)               🔧 未提交         │
│  └── L3B Message Pool (Hot Ring + SQLite)    🔧 未提交         │
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
│  ├── tool_spec.py (registry + mute)          ✅                │
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
│  ├── config_handlers.py (22 handlers)        ✅ (刚 +loop)     │
│  ├── settings_center.py (3-layer)            ✅ (刚 +loop)     │
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
│  ├── subagent*.py / l3a/3b                   ✅                │
│  ├── identity.py (Ed25519 keys)              ✅                │
│  ├── wiring.py (port→adapter assembly)       ✅                │
│  ├── acb.py (Agent Control Block)            ✅                │
│  ├── package_manager.py (apt/pip/npm)        ✅                │
│  ├── 13 more files...                        ✅                │
```

## L4 Bridge — 45 files, 9,141 lines ✅

```
│  ├── api_gateway.py (HTTP + Middleware)      ✅                │
│  ├── api_handlers/ (mixed-in, 35 categories) ✅                │
│  ├── api_routes.py (153 routes)              ✅                │
│  ├── api_middleware.py (CORS/Locale/Body)    ✅                │
│  ├── llm.py / llm_base / llm_providers       ✅                │
│  ├── llm_worker/ (RPC worker)                ✅                │
│  ├── sandbox/ (COW isolation + server)       ✅                │
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
│  L3A: 用户画像 / 习惯学习                    ⬜                │
│  L3C: Behavior Collector                     ⬜                │
│  Heavy Desktop (Electron/Tauri)              ⬜                │
│  Lightweight Desktop (对话 + diff)           ⬜                │
│  VSCode Extension                            ⬜                │
│  Multi-cluster / Distributed                 ⬜                │
│  License/Authorization system                ⬜                │
```

## Summary

```
Layer       Files    Lines    Status
─────────────────────────────────────────
L1 Kernel    37     8,497    ✅ Complete
L2 Shell     10     1,977    ✅ Complete
L3 Cell     148    31,293    ✅ Core + ◐ A/B/L3B + 🔧 HTN/CellCache
L4 Bridge    45     9,141    ✅ Complete
L5 User       2       472    ✅ Complete
tests        95    15,541    ✅ Core pass (94/94)
config        3       865    ✅ Complete
─────────────────────────────────────────
Total       340    67,786

Completed:        ~90% (L1/L2/L4/L5 + L3 core)
Partial:          ~5%  (L3A intent, HTN-A/B, L3B composites)
Uncommitted:      ~3%  (CellCache, HTN-A/B, L3B Bus/Pool, path fixes)
Not started:      ~2%  (L3C, Desktops, VSCode, License)
```
