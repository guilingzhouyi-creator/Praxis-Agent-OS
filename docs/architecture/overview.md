# Praxis Agent OS — Architecture Overview

> **Audience:** Anyone learning Praxis. 5 min read.  
> **Corresponds to:** `src/l1/` through `src/l5/` layers.

## What is Praxis?

Praxis is an **Agent Operating System** — a five-layer runtime for building, orchestrating, and controlling LLM-based AI agents. It maps traditional OS concepts (kernel, shell, process, memory, file system, security) onto the agent domain.

```
                    ┌─────────────────────────────────────┐
                    │  L5  User Layer  (cli, agent_runtime) │
                    ├─────────────────────────────────────┤
                    │  L4  Bridge Layer (API, LLM, Sandbox)│
                    ├─────────────────────────────────────┤
                    │  L3  Cell Layer   (agents, memory)   │
                    ├─────────────────────────────────────┤
                    │  L2  Shell Layer  (commands, i18n)   │
                    ├─────────────────────────────────────┤
                    │  L1  Kernel Layer (sync, gatechain)  │
                    └─────────────────────────────────────┘
```

## Five-Layer Architecture

### L1 — Kernel (`src/l1/kernel/`)

The bare-metal layer providing OS primitives:

| Subsystem | File | Purpose |
|-----------|------|---------|
| Sync | `sync.py` | Mutex, Semaphore, Barrier, RWLock, Condition |
| Process | `process.py` | ProcessTable, PCB (identity, state, resources) |
| Allocator | `allocator.py` | Token/ring/sandbox quota allocation, GC, swap |
| Event | `event.py` | EventBus pub/sub with history |
| GateChain | `gatechain.py` | G1-G5 tool authorization chain |
| Constitution | `constitution.py` | Constitutional rules engine — highest authority |
| VFS | `vfs.py` | Virtual file system with ring-level access control |
| IPC | `ipc.py` | Kernel message passing (LockChannel) |
| Device | `device.py` | Device manager (LLM, DB, network) |
| Net | `net.py` | Cross-Cell UDP/TCP mesh |
| Swapper | `swapper.py` | Background memory pressure management |
| Reputation | `reputation.py` | Agent trust scores [0.0, 1.0] |
| ToolChain | `tool_chain.py` | HMAC-SHA256 fingerprint chain |
| Commands | `commands.py` | YAML-driven command definition registry |
| Prompts | `prompts.py` | YAML-driven prompt template registry |
| OS | `os.py` | Lifecycle coordinator (boot/shutdown/restart) |
| Errors | `errors.py` | Centralized error system — 20 error codes |
| Ports | `ports.py` | Hexagonal architecture port interfaces (7 ports) |
| Params | `params/` | 589 Final constants across 5 sub-modules |

**Constants** (`src/l1/kernel/params/`):

| Sub-module | Constants | Coverage |
|-----------|-----------|----------|
| `kernel.py` | 129 | Allocator, sync, process, gatechain, vfs, syscall |
| `agent.py` | 153 | Roles, terminal, loop, scout, card, events |
| `tool.py` | 33 | Danger levels, timeouts, rate limits, HTN |
| `api.py` | 111 | API, LLM, network, IPC, env vars, CORS |
| `system.py` | 163 | Cache, persistence, memory rings, data paths, sandbox |

```python
# Import directly from sub-modules (no re-exports)
from l1.kernel.params.kernel import ALLOCATOR_DEFAULTS
from l1.kernel.params.agent import DEFAULT_CELL_ID
```

**Error codes** (`l1/kernel/errors.py`): 20 standardized error codes — `E_INTERNAL`, `E_TIMEOUT`, `E_CONSTITUTION_BLOCKED`, `E_GATECHAIN_BLOCKED`, `E_TOOL_MUTED`, `E_RESOURCE_EXHAUSTED`, `E_CELL_EMERGENCY`, etc.

### L2 — Shell (`src/l2/`)

Human interface layer for controlling agents and the system:

| Module | Lines | Purpose |
|--------|-------|---------|
| `l2_shell/__init__.py` | 87 | Command dispatch, direct/indirect message routing |
| `l2_shell/commands.py` | 764 | 39 command handlers + `_pipeline()` |
| `l2_shell/completer.py` | 67 | Tab auto-completion |
| `l2_shell/state.py` | 27 | ShellState (L3A/Direct mode) |
| `l2_shell/output_guard.py` | 15 | Output guard for dangerous responses |
| `i18n.py` | 62 | Internationalization via I18nPort |
| `selector.py` | 199 | Agent pre-select / connectivity check |
| `shell.py` | 199 | Shell entry point |
| `shell_session.py` | 129 | Session lifecycle management |
| `shell_completer.py` | 34 | Shell auto-completion engine |

**Commands:**
```
Session:      /help  /agents  /connect  /disconnect  /mode  /status
Control:      /intents  /scheduler  /observe  /skills  /cells  /cross  /security
Memory:       /memory
System:       /process  /vfs  /cache  /sysinfo  /clear  /history  /lang
Agent/Cell:   /spawn  /kill  /destroy  /emergency  /cluster  /cell_create  /agent_refresh
Audit/Config: /audit  /settings  /devices  /tools  /config
Extensions:   /cron  /buffer  /card  /tokens
```
Total: **39 commands** + pipeline `|` operator (auto Map/Chain/Passthrough) + `--cell X --agent Y` scoping.

### L3 — Cell (`src/l3/`)

The agent execution layer — ~130 files, ~19,000 lines. Core responsibilities:

| Category | Key Files | Purpose |
|----------|-----------|---------|
| **Cell** | `cell/__init__.py` | Agent collaboration unit — 28 methods |
| **Terminal** | `agent_terminal/__init__.py` | Per-agent worker process — 20+ methods |
| **Memory** | `memory.py`, `memory_init.py`, `memory_ring.py` | 3-ring memory + quality scoring |
| **Cards** | `card*.py` (10 files) | Card lifecycle, registry, gate, builder, pool |
| **Boot** | `boot.py`, `boot_init.py`, `bootstrap.py` | System bootstrap — 5 boot steps |
| **Tools** | `tools/` (16 files) | 35+ tool implementations |
| **Pipeline** | `tool_pipeline.py`, `tool_spec.py` | Ring-gated tool execution (9 steps) |
| **Scheduler** | `scheduler*.py` (5 files) | Multi-dimensional scheduling |
| **Scout** | `scout.py` | Read-only investigation pool |
| **Error** | `error_bus/` | Unified error logging + API |
| **Monitor** | `monitor_bus.py` | Monitoring event bus + JSONL persistence |
| **Config** | `config*.py`, `config_loader.py` | YAML configuration + hot-reload |
| **Execution** | `execution_*.py` (3 files) | Execution engine, plan, verification |
| **Agents** | `agent_loop.py`, `r4_agent.py`, `subagent*.py` | Agent loops, R4 archivist, sub-agents |
| **Security** | `central_security.py`, `content_trust.py` | Security checks, content provenance |
| **Queue** | `pending_queue.py`, `approval_gate.py` | Human approval queues |
| **State** | `statecharts.py` | 5-region orthogonal state machine |
| **Log** | `log.py` | Log service + rotation + API |
| **Think** | `think_registry.py` | Three-layer think quota config |
| **Convergence** | `convergence.py` | Convention → ExecutionCard pipeline |
| **Policy** | `tool_policy.py`, `message_gate.py` | Tool visibility policy, message policy |
| **Buffer** | `resource_buffer/` | Ring file buffer (stage/commit/diff/discard) |
| **Context** | `context.py`, `context_pool.py` | Context register, per-agent context pool |

### L4 — Bridge (`src/l4/`)

External interface layer — 45 files, ~6,500 lines:

| Module | Lines | Purpose |
|--------|-------|---------|
| `api_gateway.py` | 326 | HTTP server + MiddlewareChain |
| `api_handlers/__init__.py` | 587 | API handler mixin (35 categories) |
| `api_routes.py` | 197 | **153 route definitions** |
| `api_handlers_*.py` | 4 files | Cards, monitor, agent, config handlers |
| `api_middleware.py` | 233 | CORS, Locale, BodyParser, RequestLog middleware |
| `llm.py` + `llm_base.py` + `llm_providers.py` | 870 | LLM Engine + providers (OpenAI/Anthropic/Ollama) |
| `llm_worker/` | 88 | LLM worker process (RPC) |
| `sandbox.py` + `sandbox/` | 501 | Copy-on-write process isolation |
| `mcp_bridge.py` | 500 | MCP protocol ↔ ToolSpec adapter |
| `lsp_manager.py` + `lsp.py` | 737 | LSP integration |
| `rpc/` | 63 | Inter-process RPC framework |
| `supervisor.py` | 188 | Process supervisor |
| `adapters/` | 6 files | Port implementations (ThreadPool, RingChannel, etc.) |
| `credential_vault.py` | 171 | AES-256 credential store |
| `sse_bridge.py` | 106 | SSE event streaming |
| `search_engine.py` | 469 | Full-text search |

**API Routes:** 153 routes across 35 categories — cards, agents, cells, memory, tools, tokens, cron, credentials, bootstrap, error bus, logs, config, file editor, LSP, prompts, search, session, monitor, resource buffer.

### L5 — User (`src/l5/`)

| File | Lines | Purpose |
|------|-------|---------|
| `cli.py` | 259 | Typer-based CLI (boot, status, execute) |
| `agent_runtime.py` | 142 | Runtime loop (constitution → gatechain → memory → execute) |

## Layer Import Rules

```
L5 → can import L4, L3, L2, L1
L4 → can import L3, L2, L1
L3 → can import L2, L1
L2 → can only import L1
L1 → cannot import any upper layer
```

Enforced by `tests/test_layer_imports.py`. 49 pre-existing cross-layer imports are explicitly allowlisted (adapter patterns + LLM calls).

## Core Concepts

### Cell = CPU Core

| Computer Concept | Praxis Equivalent |
|-----------------|-------------------|
| CPU instruction set | ToolSpec (name / params / handler) |
| CPU core | Cell (card queue + AgentTerminal + AgentLoop) |
| Operating system | 10 Central Control Systems |
| Memory hierarchy | Memory rings R1/R2/R3 |
| MMU / page tables | Territory (constitution) + GateChain G3 |
| System calls | tool_pipeline.execute() (9 steps) |
| Device drivers | ToolSpec middleware + plugin system |
| Interrupt controller | EventBus SignalType |
| Multi-core interconnect | L3B cross-cell routing |

### Agent = Process

| OS Process | AgentTerminal |
|-----------|---------------|
| PCB | agent_id + role + ring + status |
| stdin/stdout/stderr | TerminalCard deque + CardResult deque |
| Thread pool | `_workers: list[thread]` (`_max_workers=4`) |
| PID | agent_id (string) |
| State | BOOTING → IDLE → PROCESSING → CRASHED |
| Signals | pause / resume / shutdown / emergency_stop |
| Resource limits | Allocator (tokens) + resource limiter |
| Scheduler | scheduler_*.py (rate, time, scope, router) |

### Memory = Three Rings

| Ring | Budget | Slots | TTL | Storage |
|------|--------|-------|-----|---------|
| 1 (Working) | 8K tokens | 32 | 30 min | In-memory queue |
| 2 (Short-term) | 32K tokens | 200 | 24 h | JSONL file |
| 3 (Long-term) | 128K tokens | 1000 | ∞ | SQLite + FTS5 |

Each memory entry (`MemEntry`) carries `agent_id`, `cell_id`, `entry_type`, `importance` score, and `provenance`.

### Security = Three Layers

1. **Constitution** — `constitution.py` parses `.nomos-rules.md`, enforces 14+ built-in rules
2. **GateChain G1-G5** — Non-bypassable tool authorization with `GateStatus` (PASS/WARN/BLOCK/REPORT)
3. **Tool Pipeline** — 9-step execution (clearance → rate limit → constitution → gatechain → allocator → request pool → file lock → execute → release)

## File Layout

```
src/
├── l1/kernel/          # 37 files — OS primitives
│   └── params/         # 5 sub-modules, 589 constants
├── l2/                 # 10 files — Shell layer (39 commands)
├── l3/                 # 130+ files — Cell layer
│   ├── cell/           # Cell orchestration
│   ├── agent_terminal/ # Agent workers
│   ├── error_bus/      # Error logging
│   ├── resource_buffer/# File buffer
│   └── tools/          # Tool implementations
├── l4/                 # 45 files — Bridge layer
│   ├── api_handlers/   # API mixin
│   ├── sandbox/        # Process isolation
│   ├── rpc/            # RPC framework
│   ├── adapters/       # Port implementations
│   └── llm_worker/     # LLM worker process
└── l5/                 # 2 files — User layer

tests/
└── test_layer_imports.py  # Layer constraint enforcement
```

## Quick Start

```bash
# Boot the system
python -m l5.cli boot

# Enter L2 Shell
python -m l2.l2_shell

# API (once booted)
curl http://localhost:8080/api/health
```
