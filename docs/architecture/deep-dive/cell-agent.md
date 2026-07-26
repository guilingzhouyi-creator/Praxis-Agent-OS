# Cell & Agent Architecture

> **Sources:** `src/l3/cell/__init__.py`, `src/l3/agent_terminal/__init__.py`

## Overview

The Cell is the **CPU core** of Praxis. It holds N AgentTerminals (execution units), a shared ScoutPool, an inter-agent mailbox, and snapshot/rollback capability.

| CPU Core Concept | Cell Equivalent |
|-----------------|----------------|
| Instruction pipeline | Card phases/steps |
| Register file | `agent_map` (role → agent_id) |
| Cache L1/L2/L3 | Memory rings R1/R2/R3 |
| Hyper-threading | Multi-agent parallel phase execution |
| Interrupt controller | EventBus SignalType |
| Memory controller | CentralMemory |

## Cell (`l3/cell/__init__.py`)

### 28 Public Methods

| Method | Purpose |
|--------|---------|
| `add_agent(agent_id, role, ...)` | Register a new agent |
| `remove_agent(agent_id)` | Remove agent, clean memory + context |
| `save_state(path)` | Persist to JSON |
| `restore_state(path)` | Restore from JSON |
| `send_message(sender, target, ...)` | Agent-to-agent message |
| `read_messages(agent_id)` | Read mailbox |
| `agent_reachable(agent_id)` | Ping terminal |
| `send_direct_message(agent_id, text)` | Stdin message |
| `liveness()` | Aggregate health |
| `agent_status(agent_id)` | Single agent status |
| `on_boot/on_shutdown/on_spawn/on_kill(hook)` | Lifecycle hooks |
| `boot_agent/boot_all(agent_id)` | Start agents |
| `shutdown_all()` | Stop all agents |
| `emergency_stop()` | Halt all operations (emergency flag) |
| `resume()` | Clear emergency flag |
| `reset_agent_context(agent_id)` | Clear working memory |
| `dispatch_card(target, action, ...)` | Dispatch TerminalCard |
| `convene(issue_card)` | Multi-agent convention |
| `close_convention(card_id)` | End convention |
| `handle_convention_message(...)` | Route convention message |
| `execute_card(card, domain, ...)` | Execute a Card |
| `rollback_card(card_id)` | Rollback execution |
| `decompose_card(card, domain)` | Decompose by territory |
| `agent_tools/cell_tools()` | List available tools |
| `wait_for_card(card_id, timeout)` | Block for result |
| `stats()` | Cell snapshot |

### Factory Functions

```python
get_cell(cell_id, territory)       # Singleton factory
get_cells()                         # All registered Cells
reset_cells()                       # Clear registry
```

## AgentTerminal (`l3/agent_terminal/__init__.py`)

### Architecture

```
AgentTerminal = Execution Unit
├── stdin: deque[TerminalCard]          # max=200
├── stdout: deque[CardResult]           # max=500
├── stderr: list[str]                   # max=200
├── workers: list[thread] (max=4)
├── file_cache: IsolatedCache (per-cell)
├── context: ContextRegister (per-cell)
├── scout_pool: shared pool
├── todo_table: TodoTable
└── output_guard: guard_output()
```

### 20+ Public Methods

| Method | Purpose |
|--------|---------|
| `boot()` | Constitution check → warm memory → register context → start workers |
| `set_tool_registry(registry)` | Set tool spec registry |
| `list_tools()` | Tools visible to this agent |
| `dispatch(card)` | Add to stdin queue |
| `wait_for_result(card_id, timeout)` | Block for result |
| `read_stdout/read_stderr(clear)` | Read output queues |
| `add_todo/list_todos/cancel_todo/todo_stats()` | Task management |
| `spawn_scout_async/collect_scout/collect_all_scouts()` | Async investigations |
| `set_mode(mode)` | Switch assembly/direct |
| `pause/resume()` | Suspend/resume processing |
| `shutdown()` | Stop workers, clear state |
| `session_reachable()` | Check if accepting messages |
| `send_direct_message(text, sender)` | Queue direct message |
| `status_report()` | Full state snapshot |

### Lifecycle States

```
BOOTING → IDLE → PROCESSING → CRASHED
             ↓          ↓
         BLOCKED    STOPPED
```

### Factory Functions

```python
get_terminal(agent_id, role, territory, cell_id)  # Singleton factory
get_terminals()                                      # All terminals
reset_terminals()                                    # Shutdown + clear
```

## AgentLoop (`l3/agent_loop.py`)

Wraps `LLMEngine.tool_use()` with self-correction:

- **ToolLoopDetector** — identical SHA256 tool call ×3 → WARN, ×4 → STOP
- **CoarseRepeatDetector** — same tool name ×3 → NUDGE, ×6 → STOP
- **TodoTracker** — checks for open items after LLM responds
- **VerifyCadence** — write_file/edit_file → nudge build/check

## Convention Protocol

`Cell.convene()` initiates a multi-agent meeting for card resolution:

1. L3A submits IssueCard
2. Cell dispatches to involved agents
3. Agents discuss via mailbox messages
4. `convergence.py` reads discussion → generates convergence summary
5. `Convergence.to_execution_card()` → creates ExecutionCard

## Key Constants

| Constant | Value | Use |
|----------|-------|-----|
| `CELL_ROLLBACK_RING_SIZE` | 20 | Rollback context entries |
| `CELL_HISTORY_RING_SIZE` | 100 | Card history entries |
| `CELL_SNAPSHOT_MAX` | 50 | File snapshots before cleanup |
| `CELL_MAILBOX_MAX_PER_AGENT` | 100 | Max queued messages |
| `CELL_MAILBOX_TTL` | 3600s | Message TTL |
| `TERMINAL_MAX_WORKERS` | 4 | Thread pool size |
| `AGENT_LOOP_DEFAULT_STEPS` | 10 | LLM turns per loop |
| `AGENT_LOOP_DEFAULT_TIMEOUT` | 120s | Per-loop timeout |
