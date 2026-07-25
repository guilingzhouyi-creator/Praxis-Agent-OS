# Praxis Agent OS — Technical Architecture

> NOMOS Praxis v0.3.0 codename "Aether"  
> Based on `src/` (commit: current working tree).  
> All references are to `src/main.py`, `src/kernel/`, `src/services/`, `src/tools/`, `src/tool_ring.py`, etc.

---

## 0. Architecture Overview

Praxis Agent OS maps to traditional computer architecture:

```mermaid
flowchart LR
    subgraph App["Application Layer"]
        L2["L2 Shell / API Gateway"]
        L3A["L3A Intent Parser"]
    end
    subgraph Centers["10 Central Control Systems"]
        CC["CentralController"]
        CS["CentralScheduler"]
        OB["ObservabilityBus"]
        R4["R4Agent"]
        CM["CellMonitor"]
        L3B["L3B"]
        CSEC["CentralSecurity"]
        CMEM["CentralMemory"]
        CPLUG["CentralPlugin"]
        CCOL["CentralCollector"]
    end
    subgraph Cell["Cell = CPU Core"]
        CQ["Card Queue"]
        AT["AgentTerminal xN"]
        AL["AgentLoop"]
        MB["Mailbox"]
    end
    subgraph Kernel["Kernel Layer"]
        KERN["25 modules\nsync / process / allocator\nevent / gatechain / vfs\nconstitution / ipc / net..."]
    end
    subgraph Tools["Tool Layer"]
        T37["37 tool modules"]
        TREG["ToolSpec Registry"]
        TP["ToolPipeline (7 gates)"]
    end
    App --> Centers
    Centers --> Cell
    Cell --> Kernel
    Cell --> Tools
```

| Computer Concept | Praxis Equivalent |
|---|---|
| CPU instruction set (ISA) | ToolSpec (name / params / handler) |
| CPU core | Cell (card queue + AgentTerminal + AgentLoop) |
| Operating system | 10 Central Control Systems |
| Memory hierarchy L1/L2/L3 | Memory rings R1/R2/R3 |
| MMU / page tables | Territory (constitution) + GateChain G3 |
| System calls | tool_pipeline.execute() (7 gates) |
| Device drivers | tool_spec.py middleware + plugin system |
| Interrupt controller | EventBus SignalType |
| Multi-core interconnect | L3B cross-cell routing |

---

## 1. Layered Architecture

```mermaid
flowchart TB
    subgraph Entry["Entry Layer"]
        CLI["main.py\nCLI REPL"]
        L2SH["l2_shell.py\nL2 Shell (/commands)"]
        GW["api_gateway.py\nHTTP Gateway\n129 routes"]
    end

    subgraph Centers["10 Central Control Systems"]
        CTRL["CentralController\nl3.py\nIntent lifecycle"]
        SCHED["CentralScheduler\nscheduler.py\n5D scheduling"]
        OBS["ObservabilityBus\nobservability_bus.py\nAlert/Health/Metric"]
        R4A["R4Agent\nr4_agent.py\nArchive + Skills"]
        CMON["CellMonitor\ncell_monitor.py\nHealth events"]
        CB["L3B\nl3b.py\nCross-cell routing"]
        CSEC["CentralSecurity\ncentral_security.py\n6-gate check"]
        CMEM["CentralMemory\ncentral_memory.py\nR1-R4 coordinator"]
        CPLUG["CentralPlugin\ncentral_plugin.py\nPlugin lifecycle"]
        CCOL["CentralCollector\ncentral_collector.py\nToken aggregation"]
    end

    subgraph Cell["Cell = CPU Core (services/cell.py)"]
        CQ["Card Queue\npriority-sorted"]
        AGT["AgentTerminal xN\nworker threads"]
        AL["AgentLoop\nLLM tool calling"]
        MB["Mailbox\nCellMessage"]
        SCT["ScoutPool\nread-only"]
    end

    subgraph Kernel["Kernel Layer (src/kernel/)"]
        SYNC["sync.py\nMutex/Semaphore/Barrier/Condition/RWLock"]
        PROC["process.py\nProcessTable"]
        ALLOC["allocator.py\nToken allocator"]
        GATE["gatechain.py\nG1-G5"]
        CONST["constitution.py\nRules engine"]
        EVT["event.py\nEventBus"]
        VFS["vfs.py\nVirtual FS"]
        IPC["ipc.py\nLockChannel"]
        DEV["device.py\nDevice manager"]
        NET["net.py\nTCP/UDP mesh"]
        SWAP["swapper.py\nRing swapper"]
        REP["reputation.py\nAgent scores"]
    end

    subgraph Tools["Tool Layer (src/tools/)"]
        BASE["base/\n15 modules"]
        ADV["advanced/\n15 modules"]
        CELLT["cell/\n4 modules"]
        SPEC["special/\n3 modules"]
    end

    Entry --> Centers
    Centers --> Cell
    Cell --> AgentLoop
    AL -->|"engine.tool_use()"| LLM["LLM Engine"]
    AL -->|"pipeline.execute()"| TP["ToolPipeline\n7 gates"]
    TP --> Tools
    Cell --> Kernel
```

---

## 2. Boot Sequence

```mermaid
sequenceDiagram
    participant CLI as main.py
    participant OS as kernel/os.py:OS
    participant BOOT as services/boot.py
    participant CFG as config_loader.py
    participant K as Kernel Modules
    participant CELL as services/cell.py
    participant REG as CardRegistry
    participant CTRL as CentralController

    CLI->>OS: python main.py boot
    OS->>BOOT: OS.boot(agent_config)

    BOOT->>BOOT: 1. load_constitution()
    Note over BOOT: Constitution rules engine

    BOOT->>CFG: 2. load_config()
    Note over CFG: 22 config handlers run:<br/>kernel, llm, cache, network, api,<br/>prompts, commands, card_types, mcp,<br/>credentials, gatechain, constitution,<br/>agents, clearance, territories, devices,<br/>tool_rates, htn, persist, card_gate, api_routes

    BOOT->>K: 3. _init_kernel_and_vfs()
    K-->>BOOT: sync, event_bus, allocator,<br/>gatechain, swapper, vfs,<br/>device_manager, constitution,<br/>settings, health

    BOOT->>BOOT: 4. _init_skills_and_network()
    Note over BOOT: skills, HTN planner, network mesh

    BOOT->>BOOT: 5. _init_memory_and_archive()
    Note over BOOT: Memory rings R1-R3<br/>R4Agent archive daemon<br/>IssueTable + CacheDocument<br/>CredentialVault (AES-256)<br/>ToolMode init<br/>CentralSecurity/CentralMemory/CentralPlugin

    BOOT->>CELL: 6. create_cell()
    CELL->>CELL: add_agent(agent_id, role, territory)
    CELL->>CELL: AgentTerminal.boot() -> IDLE
    CELL->>CELL: ScoutPool init
    CELL->>REG: register_cell() + start_dispatcher()

    BOOT->>CTRL: 7. CentralController init
    CTRL->>REG: Cell registered, dispatcher polling
    Note over REG: Background thread polls every 1s<br/>routes cards via Card Gate

    OS-->>CLI: Boot OK → {success, elapsed, agents}
```

---

## 3. Agent Execution Flow

### 3a. Agent Execution Flow (`tool_pipeline.execute()`)

```mermaid
flowchart LR
    subgraph Input["Input"]
        ACTION["Action\n(type, target, params)"]
    end

    subgraph Chain["Enforcement Chain"]
        direction TB
        C1["1. Constitution Check\nconstitution.is_allowed()"]
        C2["2. GateChain G1-G5\ngatechain.check()"]
        C3["3. Memory Refeed\nbuild_context()"]
        C4["4. Allocator Check\nallocator.alloc(tokens)"]
        C5["5. Resource Check\nlimiter.check(workers)"]
        C6["6. File Locks\nrwlock.read/write_lock()"]
        C7["7. Execute\nToolSpec.handler()"]
        C8["8. Memory Store\nmemory.remember(Ring1)"]
        C9["9. Release\nlocks + workers"]
    end

    subgraph Output["Output"]
        RESULT["{success, data, fingerprint, ticks}"]
    end

    ACTION --> C1
    C1 -->|BLOCKED| RESULT
    C1 -->|PASS| C2
    C2 -->|BLOCKED| RESULT
    C2 -->|PASS| C3
    C3 --> C4
    C4 -->|EXHAUSTED| RESULT
    C4 -->|OK| C5
    C5 --> C6
    C6 --> C7
    C7 --> C8
    C8 --> C9
    C9 --> RESULT
```
### 3b. AgentLoop Multi-Turn (`services/agent_loop.py`)

The AgentLoop wraps `LLMEngine.tool_use()` with four self-correction and verification mechanisms:

```mermaid
flowchart TB
    subgraph AL["AgentLoop.run()"]
        SYS["Build system prompt\n+ role resolution + todo reminder"]
        SYS --> REG["Register todowrite tool\n+ user tools"]
        REG --> MAIN["LLM tool_use() call\nmax_steps turns"]
        MAIN --> PROCESS["Process each tool result:"]

        subgraph Checks["Per-Result Checks (in order)"]
            EXACT["1. ToolLoopDetector (exact)\nSHA256(tool+args+result)\nWARN at 3 / STOP at 4"]
            COARSE["2. CoarseRepeatDetector\nSame tool name regardless of args\nNUDGE at 3 / STOP at 6"]
            CADENCE["3. VerifyCadence\nTrack write_file/edit_file\n→ nudge build/check if unverified"]
            VERIFY["4. Self-Verification\nLLM check result vs goal\nor rule-based fallback\nMAX_SELF_HEAL=3 corrections"]
        end

        PROCESS --> EXACT
        EXACT -->|STOP| BREAK["break — _loop_stopped"]
        EXACT -->|continue| COARSE
        COARSE -->|STOP| BREAK
        COARSE -->|NUDGE| CADENCE
        COARSE -->|continue| CADENCE
        CADENCE --> VERIFY

        subgraph Continuation["Post-Turn Continuations"]
            TODO["TodoTracker.has_open_items()?\n→ nudge continue"]
            CAD_NUDGE["VerifyCadence.nudge()?\n→ nudge build/check"]
        end

        VERIFY --> POST["All results processed"]
        POST --> TODO
        TODO --> CAD_NUDGE
        CAD_NUDGE --> CONT["engine.generate(nudge)\nappend to answer"]
    end

    BREAK --> RESULT["{success, answer, steps,\nverifier_used, corrections,\nloop_stopped}"]
    CONT --> RESULT
```

#### Inner Components

| Component | Lines | Trigger | Action |
|-----------|-------|---------|--------|
| **ToolLoopDetector** | `agent_loop.py:29` | Consecutive identical (tool+args+result) ×3 | WARN: inject course-correction nudge |
| | | Consecutive identical ×4 | STOP: terminate turn, `_loop_stopped=true` |
| **CoarseRepeatDetector** | `agent_loop.py:72` | Same tool_name ×3 | NUDGE: "you have issued N multiple times" |
| | | Same tool_name ×6 | STOP: terminate turn |
| **TodoTracker** | `agent_loop.py:101` | Open items exist after LLM responds | Inject continuation nudge, continue loop |
| | | All items completed | No nudge, turn ends normally |
| **VerifyCadence** | `agent_loop.py:154` | write_file/edit_file without following build cmd | Nudge: "Run a fast check" (at most once per edit) |

#### Todo In-Context Reminder

Every AgentLoop call injects:
```
>> You are currently ON task 'add input validation'
Current task list:
  [✓] 1. Parse config file
  [→] 2. Add input validation
  [ ] 3. Write tests

Update ONE item at a time using 'todowrite' with status: pending|in_progress|completed
Do NOT stop while ANY item is still pending or in_progress.
```

Model manages this list via the built-in `todowrite` tool.

#### Provider Retry Layers (`services/llm.py:_call_api`)

| Layer | Detection | Backoff | Max |
|-------|-----------|---------|-----|
| Overflow | HTTP 413/400 + "too long" | compact memory + retry | 3 |
| Rate limit | HTTP 429 | Retry-After header or 60s | 5 |
| Transient | timeout/reset/refused/5xx | Linear 3/6/9s | 3 |
| Empty | 200 OK, no content, no tool_calls | 1/1/2/2/3s | 5 |

---

## 4. GateChain G1-G5 Authorization

```mermaid
flowchart LR
    subgraph G1["G1: Tool Whitelist"]
        direction TB
        G1_IN["Tool name in TOOL_REGISTRY?"]
        G1_PASS["PASS"]
        G1_BLOCK["BLOCK"]
        G1_IN -->|Yes| G1_PASS
        G1_IN -->|No| G1_BLOCK
    end

    subgraph G2["G2: Identity"]
        direction TB
        G2_IN["Agent in ProcessTable?\nState READY/RUNNING?"]
        G2_PASS["PASS + Ed25519?"]
        G2_BLOCK["BLOCK"]
        G2_WARN["WARN\n(no keypair)"]
        G2_IN -->|Yes + key| G2_PASS
        G2_IN -->|Yes no key| G2_WARN
        G2_IN -->|No| G2_BLOCK
    end

    subgraph G3["G3: Territory + Risk"]
        direction TB
        G3_IN["Target in Territory?\nRisk = danger + freq×0.5"]
        G3_IN -->|In territory + risk<6| G3_PASS["PASS"]
        G3_IN -->|In territory + risk>=6| G3_WARN["WARN"]
        G3_IN -->|Outside territory| G3_BLOCK["BLOCK"]
    end

    subgraph G4["G4: Escalation"]
        direction TB
        G4_IN["Danger >= 4?"]
        G4_IN -->|Yes| G4_WARN["WARN + L3 Notified"]
        G4_IN -->|No| G4_PASS["PASS"]
    end

    subgraph G5["G5: Composite Judgment"]
        direction TB
        G5_IN["Score = danger×2 + history×0.5 + freq×1.0\nReputation [0.0-1.0]"]
        G5_IN -->|rep>=0.9 + G3=WARN| G5_PASS["PASS (high tolerance)"]
        G5_IN -->|rep<0.7 + G3=WARN| G5_BLOCK["BLOCK"]
        G5_IN -->|repeated + high freq| G5_REPORT["REPORT"]
        G5_IN -->|normal| G5_PASS2["PASS"]
    end

    TOOL["Tool Call"] --> G1
    G1 -->|PASS| G2
    G1 -->|BLOCK| STOP["STOP ✗"]
    G2 -->|PASS/WARN| G3
    G2 -->|BLOCK| STOP
    G3 -->|PASS/WARN| G4
    G3 -->|BLOCK| STOP
    G4 -->|PASS/WARN| G5
    G5 -->|PASS| ALLOW["ALLOW ✓"]
    G5 -->|WARN| ALLOW
    G5 -->|BLOCK/REPORT| STOP
```

---

## 5. Tool Pipeline

```mermaid
flowchart TB
    subgraph Pipeline["Tool Pipeline (tool_pipeline.py)"]
        direction TB
        S1["1. Clearance Check\nagent.ring >= tool.ring"]
        S2["2. Rate Limit\ncalls/min per ring\nRing1=60, R2.5=20, R3=5"]
        S3["3. Constitution Check\nis_allowed(action, agent, target=FILE_PATH)"]
        S3B["3b. GateChain G1-G5\nG1: whitelist\nG2: process + identity\nG3: territory + risk\nG4: escalation\nG5: reputation + loop"]
        S4["4. Allocator\nalloc(tokens)"]
        S5["5. Request Pool\nRing 2.5:\nreputation-weighted\nscheduling"]
        S6["6. File Lock\nrwlock.write_lock()"]
        S7["7. Execute\nToolSpec.handler()"]
        S8["8. Release\nunlock + free + audit"]
    end

    S3 --> S3B
    S3B --> S4
    Pipeline --> RING1["Ring 1 (Read-Only)\nrecord ToolCallRecord"]
    Pipeline --> RING2["Ring 2.5 (Write)\nRequestPool dequeue"]
    Pipeline --> RING3["Ring 3 (Destructive)\nWitness via IPC"]
```

---

## 6. Tool Ring Architecture

```mermaid
classDiagram
    class ToolCallRecord {
        +str tool_name
        +str agent_id
        +bool success
        +str gate_result
        +str fingerprint
        +str error
        +str timestamp
    }

    class ToolRing {
        -deque[ToolCallRecord] _records
        +int capacity
        +record(entry)
        +recent(n) list
        +count() int
        +gate_stats() dict
    }

    class ToolRequest {
        +str tool_name
        +str agent_id
        +int priority
        +float agent_reputation
        +int tool_danger
        +float enqueued_at
    }

    class RequestPool {
        -list[ToolRequest] _requests
        +int capacity
        +enqueue(request) bool
        +dequeue() ToolRequest
        +peek() list
        -_score(r) float
    }

    ToolRing o-- ToolCallRecord
    RequestPool o-- ToolRequest
```

---

## 7. Tool Registry & Mute System

Tools are registered in a global `TOOL_REGISTRY: dict[str, ToolSpec]` and auto-discovered from 4 directories (`tools/base/`, `tools/cell/`, `tools/advanced/`, `tools/special/`). The mute system adds runtime disable capability at four independent levels.

### 7.1 Mute Levels

```mermaid
flowchart TB
    subgraph Registry["Tool Registry (tool_spec.py)"]
        REG["TOOL_REGISTRY\ndict[str, ToolSpec]"]
        PLUGIN["_PLUGIN_REGISTRY\nplugin → tool list"]
        MUTED["_MUTED: set[str]\n_MUTED_CATEGORIES: set[str]\n_MUTED_PLUGINS: set[str]\n_MUTED_RINGS: set[str]"]
    end

    subgraph Levels["Four Mute Levels (OR)"]
        T["mute_tool('run_in_terminal')\nSingle tool granular"]
        C["mute_category('network')\nEntire category"]
        P["mute_plugin('docker')\nThird-party plugin"]
        R["mute_ring('ring_3')\nAll destructive tools"]
    end

    subgraph CheckPoints["Runtime Check Points"]
        EXEC["tool_spec.execute_tool_spec()\n→ if is_muted: return muted error"]
        LIST["agent_terminal.list_tools()\n→ filter is_muted"]
        LOOP["_term_handlers.handle_think()\n→ skip add_tool for muted"]
    end

    MUTED --> T
    MUTED --> C
    MUTED --> P
    MUTED --> R
    T --> EXEC
    C --> EXEC
    P --> EXEC
    R --> EXEC
    EXEC --> LIST
    LIST --> LOOP
```

### 7.2 API

| Function | Effect |
|----------|--------|
| `mute_tool("run_in_terminal")` | Disable a single tool by name |
| `unmute_tool("run_in_terminal")` | Re-enable |
| `mute_category("network")` | Disable all tools in a category |
| `unmute_category("network")` | Re-enable |
| `mute_plugin("docker")` | Disable all tools from a plugin |
| `unmute_plugin("docker")` | Re-enable |
| `mute_ring("ring_3")` | Disable all tools at a ring level |
| `unmute_ring("ring_3")` | Re-enable |
| `is_muted(tool_name)` → bool | Check at all four levels |
| `list_muted()` → dict | Show all active mute rules |
| `clear_mutes()` | Reset all |

### 7.3 Triple-Layer Enforcement

```mermaid
flowchart LR
    LLM["LLM never sees\nmuted tools"] -->|handle_think\nskip add_tool| AGENT["AgentTerminal\nnever lists\nmuted tools"] -->|list_tools\nfilter is_muted| EXEC["execute_tool_spec\nnever runs\nmuted tools"] -->|is_muted\n→ blocked| DONE["muted error\nreturned"]
```

### 7.4 Tool Discovery

```python
# tool_registry_setup.py
# Auto-discovers from 4 directories:
#   tools/base/      → Ring 1 read-only tools
#   tools/cell/      → Cell collaboration & governance
#   tools/advanced/  → Ring 2.5-3 write/destructive
#   tools/special/   → Composite, archive, L3
# Each tools_*.py exports register_tools()
# Third-party: register_plugin(name, tools, pre_hook, post_hook)
```

---

## 8. Cell & Agent Architecture

The Cell is the **CPU core** of Praxis. It holds N AgentTerminals (execution units), a shared ScoutPool, and a mailbox for inter-agent messaging.

### Cell = CPU Core Analogy

| CPU Core Concept | Cell Equivalent |
|---|---|
| Instruction pipeline | Card phases/steps (sequential or parallel) |
| Register file | `agent_map` (role → agent_id) |
| Cache L1/L2/L3 | Memory rings R1/R2/R3 |
| Branch predictor | HTN Planner intent decomposition |
| Hyper-threading | Multi-agent parallel phase execution |
| Interrupt controller | EventBus SignalType subscription |
| Memory controller | CentralMemory (R1-R4 coordinator) |

### Architecture

```mermaid
flowchart TB
    subgraph Input["Card Input (from CardRegistry)"]
        CARD_IN["execute_card(intent, domain)"]
    end

    subgraph Cell["Cell = CPU Core (services/cell.py)\ncard queue + agent map + mailbox"]
        direction TB
        AQ["Agent Queue:\n_terminal_id → AgentTerminal\n(agent_map from Card)"]
        MB["Mailbox:\nCellMessage[]\nagent-to-agent messaging"]
        SP["ScoutPool\n(shared investigation pool)"]
        SUB["SubAgent\n(sync quick-check)"]
        SNAP["Snapshot/Rollback\n(pre-exec file snapshots)"]
    end

    subgraph AgentTerminal["AgentTerminal = Execution Unit\n(services/agent_terminal.py)"]
        direction TB
        STDIN["stdin: deque[TerminalCard]"]
        STDOUT["stdout: deque[CardResult]"]
        WORKER["Worker Thread Pool\n(max_workers=4)"]
        CACHE["FileCache + ContextRegister"]
    end

    subgraph AgentLoop["AgentLoop = Microcode Sequencer\n(services/agent_loop.py)"]
        direction TB
        MAIN["run() → engine.tool_use()\nLLM multi-turn"]
        DETECT["ToolLoopDetector\nCoarseRepeatDetector"]
        TODO["TodoTracker\npersistent state machine"]
        CADENCE["VerifyCadence\nsubprocess checks"]
        FINISH["_finish()\ncentralized terminal funnel"]
    end

    subgraph Support["Support Agents"]
        SCT["Scout\nRing 1, read-only\nPool-managed"]
        SUB2["SubAgent\nRing 1, sync\nStateless"]
    end

    CARD_IN --> Cell
    Cell -->|"dispatch TerminalCard"| STDIN
    WORKER -->|"_process_card"| MAIN
    MAIN --> DETECT
    MAIN --> TODO
    MAIN --> CADENCE
    MAIN --> FINISH
    Cell --> SP
    Cell --> SUB
    Cell --> SNAP
    SP --> SCT
    SUB --> SUB2
```

---

## 9. Card Lifecycle

```mermaid
stateDiagram-v2
    [*] --> QUEUED: registry.submit()
    QUEUED --> DISPATCHED: registry.dispatch()
    DISPATCHED --> RUNNING: cell.execute_card()
    RUNNING --> DISPATCHED: decompose → sub-cards
    RUNNING --> VERIFYING: step complete
    VERIFYING --> RUNNING: verify fail → retry
    VERIFYING --> DONE: all steps + verify pass
    DONE --> [*]: registry.complete()
    RUNNING --> FAILED: unrecoverable error
    FAILED --> [*]
    QUEUED --> CANCELLED: registry.cancel()
    CANCELLED --> [*]
```

Card structure:

```mermaid
classDiagram
    class Card {
        +str id
        +str intent
        +str domain
        +CardMode mode
        +int priority
        +list[Phase] phases
        +all_steps() list[Step]
    }

    class Phase {
        +str name
        +PhaseMode mode
        +list[Step] steps
    }

    class Step {
        +str action
        +str agent
        +str target
        +dict params
        +VerifyChain verify
    }

    class VerifyChain {
        +list[VerifyStep] steps
        +verify() dict
    }

    Card o-- Phase
    Phase o-- Step
    Step o-- VerifyChain
```

### 9a. Dual-Layer Card Queue: Dispatch Queue + Card Gate

The card queue is split into two layers:

1. **Dispatch Queue** (`CardRegistry._queue`) — priority-sorted list of card IDs waiting for Cell dispatch
2. **Card Gate** (`card_gate.py`) + **PendingQueue** (`pending_queue.py`) — human/convention approval queue for cards requiring review

```mermaid
flowchart TB
    subgraph Submit["Card Submission"]
        SUBMIT["registry.submit()\n→ append to _queue\n→ sort by priority"]
    end

    subgraph Gate["CardGate (card_gate.py)"]
        CLASSIFY["classify card:\nsmall | medium | large | disputed"]
        CLASSIFY --> SMEVAL{"size evaluation"}
        SMEVAL -->|"small (<50 items)"| AUTO["auto_approve = True"]
        SMEVAL -->|"medium (50-200)"| AUTO2["auto_approve = True\n(notify L3A)"]
        SMEVAL -->|"large (>200)"| HOLD["→ PendingQueue\nawait human approval"]
        SMEVAL -->|"disputed"| HOLD
    end

    subgraph Pending["PendingQueue (pending_queue.py)"]
        ENQUEUE["enqueue(card_id, size)"]
        APPROVE["approve(card_id)\n→ callback restore_card()"]
        REJECT["reject(card_id)\n→ remove from _queue"]
        ESCALATE["escalate(card_id)\n→ convene convention"]
        EXPIRY["TTL check\nescalate stale >1h"]
    end

    subgraph Dispatch["Background Dispatcher"]
        DISPATCH["_dispatcher_loop()\nevery 1s"]
        DISPATCH --> POP["pop next pending card"]
        POP --> {"held?"}
        POP -->|"yes"| WAIT["wait for approval"]
        POP -->|"no"| SEND["cell.execute_card()"]
    end

    SUBMIT --> CLASSIFY
    AUTO --> DISPATCH
    AUTO2 --> DISPATCH
    HOLD --> ENQUEUE
    ENQUEUE --> APPROVE
    APPROVE --> DISPATCH
    ENQUEUE --> REJECT
    ENQUEUE --> ESCALATE
    APPROVE --> DISPATCH
```

**Stateful Approval Trail** on each `CardRecord`:
- `approval_status`: pending | auto_approved | human_approved | rejected | escalated
- `approval_size`: small | medium | large | disputed
- `approval_at`: ISO timestamp
- `approval_by`: agent_id or "auto"

---

## 10. Memory System Detail

### 9.1 Three Rings + Dual Storage

```mermaid
flowchart LR
    subgraph Rings["Three-Ring Memory"]
        R1["Ring 1 Working\n8K tokens / 32 slots\nIn-Memory\nCurrent card context\nTTL: 30min"]
        R2["Ring 2 Short-Term\n32K tokens / 200 slots\nJSONL Append-Only\nSession history replay\nTTL: 24h"]
        R3["Ring 3 Long-Term\n128K tokens / 1000 slots\nSQLite + FTS5\nPersistent knowledge base\nTTL: ∞"]
    end

    subgraph Storage["Dual Storage"]
        J["memory_ring2.jsonl\nOne MemEntry per line\ntail 500 = recent history"]
        S["memory_ring3.db\nSQLite + FTS5\nCREATE VIRTUAL TABLE\nknowledge_fts USING fts5"]
    end

    R2 --> J
    R3 --> S
    S --> FTS5["search_long_term()\nFTS5 MATCH query\nFull-text cross-session"]
```

### 9.2 Memory Quality System

Auto-scores each entry 0.0–1.0 on write, rejects low-quality content:

| Criterion | Bonus/Penalty | Example |
|-----------|--------------|---------|
| Type: decision/pattern | +0.3 | "use Poetry not pip" |
| Contains file path | +0.1 | "~/code/api uses Go 1.22" |
| Contains IP/version | +0.1 | "staging at 10.0.1.50" |
| Contains port | +0.05 | "SSH port 2222 not 22" |
| Contains env var | +0.05 | "DATABASE_URL=..." |
| Too short (<30 chars) | REJECTED | "read file" |
| Too long (>2000 chars) | REJECTED | raw log dump |
| Vague pattern | REJECTED | "user has a project" |

### 9.3 Auto-Compaction + Snapshot + Resume

```mermaid
flowchart TB
    START["Card Phase N completes"] --> CHECK{"memory.pressure()\n== 'high'?"}
    CHECK -->|"≥80% token usage"| SNAPSHOT["① Snapshot\ncontext.recent(20) for each agent"]
    CHECK -->|"<80%"| SKIP["Skip compact"]

    SNAPSHOT --> COMPACT["② Compact\n_suggest_compact()\nmerge 3+ related entries\n→ summary in Ring 2"]
    COMPACT --> RESUME["③ Resume\ncontext.store(restored:...)\nfor each snapshot item"]
    RESUME --> NEXT["Card Phase N+1 continues"]

    subgraph Triggers["Compaction Triggers"]
        T1["agent_terminal._execute_card()\nafter think action\nsingle-agent compact"]
        T2["execution_plan.execute()\nbetween sequential phases\ncell-wide compact"]
    end
```

### 9.4 Memory → AgentLoop Bridge

```python
# _term_handlers.py:handle_think
# Auto-inject OS-managed context on every think
memory = get_memory()
ring_context = memory.build_context(agent_id, max_tokens=1024)
recent = term.context.recent(5)

system_prompt = f"You are {agent_id} ({role}) in NOMOS Praxis.\n"
if ring_context:
    system_prompt += f"\n--- Memory Context ---\n{ring_context}\n---"

loop = AgentLoop(task=task, agent_id=agent_id, system=system_prompt)
result = loop.run(max_steps=10)

# Result auto-stored back to memory
memory.remember(agent_id, "thought", output, ring=1)
term.context.store(key=f"think:{target}", value=output)
```

---

## 11. Dual-Layer Three-Ring Composite Architecture

```mermaid
flowchart TB
    subgraph ToolRing["Tool Ring (execution security)"]
        direction TB
        TR1["Ring 1 Private\nToolCallRecord deque\nRead-only tools\nrecord() → gate_stats()"]
        TR25["Ring 2.5 RequestPool\nReputation-weighted\nrep×40% + pri×35% + wait×25%\nLowest-score evicted"]
        TR3["Ring 3 Witness\nIPC cross-review\nHuman approval via\nservices/ipc.py bus"]
    end

    subgraph MemoryRing["Memory Ring (memory storage)"]
        direction TB
        MR1["Ring 1 Working\n8K tokens in-memory\nCurrent card context\nEphemeral"]
        MR2["Ring 2 Short-Term\nJSONL append-only\nSession history replay\nTail 500"]
        MR3["Ring 3 Long-Term\nSQLite FTS5\nPersistent knowledge base\nFull-text searchable"]
    end

    subgraph Swapper["Swapper (kernel/swapper.py)"]
        SWAP_IN["swap_in()\nRing 3 → Ring 1\nOn context need"]
        SWAP_OUT["_swap_out_working()\nRing 1 → Ring 2/3\nOn pressure"]
    end

    subgraph Composite["Composite: tick() spans both layers"]
        TICK7["step 7: Execute\n→ Tool Ring\n→ GateChain G1-G5\n→ ToolSpec handler"]
        TICK8["step 8: Memory Store\n→ Memory Ring\n→ remember(Ring 1)\n→ pressure check\n→ auto-compact"]
    end

    TICK7 --> TR1
    TICK7 --> TR25
    TICK7 --> TR3
    TICK8 --> MR1
    MR1 --> SWAP_OUT
    SWAP_OUT --> MR2
    SWAP_OUT --> MR3
    SWAP_IN --> MR1
    MR3 -->|"search_long_term()\nFTS5"| MR1
```

**Tool Ring** controls whether an Agent **can** perform an operation.  
**Memory Ring** controls whether an Agent **remembers** past context.  
**Composite point** is at gent_runtime.tick() steps 7-8: within the same tick, execution passes through Tool Ring approval, results store into Memory Ring.

---

## 12. Module Dependency Map

```mermaid
flowchart TB
    subgraph KernelDeps["kernel Module Dependencies"]
        PARAMS["params.py"] --> SYNC["sync.py"]
        PARAMS --> ALLOC["allocator.py"]
        PARAMS --> CONST["constitution.py"]
        PARAMS --> GATE["gatechain.py"]
        PARAMS --> PROCESS["process.py"]
        PARAMS --> IPC["ipc.py"]
        PARAMS --> VFS["vfs.py"]

        SYNC --> IPC
        ALLOC --> PROCESS
        ALLOC --> INTERRUPT["interrupt.py"]
        GATE --> EVENT["event.py"]
        GATE --> PROCESS
        GATE --> REP["reputation.py"]
    end

    subgraph ServiceDeps["service → kernel Dependencies"]
        BOOT["boot.py"] --> PARAMS
        BOOT --> CONST
        BOOT --> VFS
        BOOT --> DEV["kernel/device.py"]
        BOOT --> NET["kernel/net.py"]
        BOOT --> SKILL["kernel/skill.py"]
        BOOT --> GATE

        CELL["cell.py"] --> EVENT
        CELL --> SYNC
        CELL --> PARAMS
        CELL --> SCOUT["services/scout.py"]
        CELL --> TERM["services/agent_terminal.py"]
    end
```

---

## 13. Key Constants (from `src/kernel/params.py`)

| Category | Examples |
|----------|----------|
| **Allocator** | `ALLOCATOR_DEFAULTS.{tokens=4096, ring1=32, ring2=200, ring3=1000}` |
| **Mutex** | `MUTEX_DEFAULT_TIMEOUT=30.0`, `MUTEX_DEFAULT_PRIORITY=5.0` |
| **Semaphore** | `SEMAPHORE_DEFAULT_MAX=3`, `SEMAPHORE_DEFAULT_TIMEOUT=30.0` |
| **Scout** | `MAX_SCOUTS_PER_AGENT=3`, `SCOUT_TIMEOUT=300.0`, `SCOUT_CACHE_TTL=30.0` |
| **Tool Timeouts** | `TOOL_TERMINAL_TIMEOUT=30.0`, `TOOL_GREP_TIMEOUT=15.0` |
| **Tool Rates** | `TOOL_RATE_RING_1=60/min`, `RING_2_5=20/min`, `RING_3=5/min` |
| **GateChain** | `GATECHAIN_RISK_WARN_THRESHOLD=6.0`, `GATECHAIN_REPEAT_THRESHOLD=5` |
| **Process** | `PROCESS_AUDIT_MAX=1000`, `PROCESS_INIT_RING=3` |
| **Network** | `BROADCAST_INTERVAL=15.0`, `PEER_TIMEOUT=60.0` |
| **Cell ID** | `DEFAULT_CELL_ID="cell-1"` |
| **Config Dir** | `PRAXIS_CONFIG_DIR=".config/nomos-praxis"` |
| **LLM URLs** | `ANTHROPIC_DEFAULT_URL="https://api.anthropic.com/v1/messages"` |
| **Memory Budget** | `working=8192, short=32768, long=131072` |
| **Memory Pressure** | `PRESSURE_HIGH=0.80, PRESSURE_MEDIUM=0.60` |

---

## 14. File Layout

```
praxis/
├── pyproject.toml              # Project config, entry: praxis=main:main
├── praxis.yaml                  # System config (constitution, gatechain, LLM, etc.)
├── .nomos-rules.md              # Constitution rules file
├── .praxis_settings.json        # Runtime settings (auto-generated)
├── .gitignore
│
├── src/
│   ├── main.py                  # CLI entry point + REPL
│   ├── cli.py                   # Typer-based CLI (hermes-like commands)
│   ├── tui.py                   # Curses TUI
│   ├── server.py                # pywebview IDE bridge
│   ├── constants.py             # Re-export bridge → kernel/params.py
│   ├── tool_ring.py             # Ring 1 + Ring 2.5 ToolRing/RequestPool
│   ├── tool_approval.py         # Ring 3 IPC witness
│   │
│   ├── kernel/                  # 25 modules — OS primitives + prompt/command registries
│   │   ├── __init__.py          # syscall dispatcher + audit trail
│   │   ├── params.py            # Single source of truth for all constants
│   │   ├── platform.py          # Cross-platform OS detection (IS_WINDOWS, SHELL, etc.)
│   │   ├── sync.py              # Mutex, Semaphore, Barrier, Condition, RWLock
│   │   ├── process.py           # ProcessTable + PCB
│   │   ├── allocator.py         # Token allocator, GC, OOM
│   │   ├── event.py             # EventBus publish/subscribe
│   │   ├── gatechain.py         # G1-G5 authorization
│   │   ├── constitution.py      # Constitution engine
│   │   ├── vfs.py               # Virtual file system
│   │   ├── ipc.py               # LockChannel + LockBus
│   │   ├── device.py            # Device manager
│   │   ├── persist.py           # SQLite event store
│   │   ├── reputation.py        # Agent reputation
│   │   ├── tool_chain.py        # HMAC-SHA256 fingerprint chain
│   │   ├── swapper.py           # Memory ring swapper
│   │   ├── settings.py          # Key-value config store
│   │   ├── skill.py             # Skill manager
│   │   ├── interrupt.py         # Interrupt table
│   │   ├── net.py               # Network kernel (UDP/TCP mesh)
│   │   ├── registry.py          # Central system registry
│   │   ├── health.py            # Kernel health check
│   │   ├── resource.py          # Resource limiter
│   │   ├── prompts.py           # YAML-driven prompt template registry
│   │   ├── commands.py          # YAML-driven command definition registry
│   │   └── os.py                # OS lifecycle coordinator
│   │
│   ├── services/                # 67 modules — higher-level services
│   │   ├── boot.py              # Boot sequence
│   │   ├── cell.py              # Agent collaboration unit (N agents + ScoutPool)
│   │   ├── cell_decompose.py    # Card decomposition by territory
│   │   ├── cell_types.py        # AgentInfo, CellMessage, MessageType, AgentRole
│   │   ├── agent_terminal.py    # Agent process + worker pool
│   │   ├── card.py              # Card data model
│   │   ├── card_registry.py     # Card queue + status
│   │   ├── card_builder.py      # Intent → Card compiler
│   │   ├── card_yaml.py         # YAML card loader
│   │   ├── l3.py                # L3 coordinator
│   │   ├── l3a.py               # L3A: Human → Card
│   │   ├── l3b.py               # L3B: Cross-cell routing
│   │   ├── llm.py               # LLM engine + tool_use() multi-turn loop
│   │   ├── llm_base.py          # LLMProvider ABC, LLMConfig, ToolSearch
│   │   ├── llm_providers.py     # Mock/OpenAI/Anthropic/Ollama providers
│   │   ├── counter.py           # Cell-level token/tool/loop counters
│   │   ├── settings_center.py   # Three-layer config (L1 params > L2 yaml > L3 json)
│   │   ├── approval_gate.py     # Human approval gate for dangerous tools
│   │   ├── mcp_bridge.py        # MCP protocol ↔ ToolSpec bidirectional adapter
│   │   ├── agent_loop.py        # AgentLoop — LLM tool-calling loop
│   │   ├── agent_terminal.py    # AgentTerminal — persistent worker process
│   │   ├── scout.py             # Scout pool (async investigation)
│   │   ├── ipc.py               # IPC protocol (20+ message types)
│   │   ├── tool_spec.py         # ToolSpec registry
│   │   ├── tool_pipeline.py     # Ring-gated tool execution
│   │   ├── scheduler.py         # Unified scheduler (L3Router + RequestPool + TimeScheduler)
│   │   ├── scheduler_router.py  # L3Router: intent → best agent routing
│   │   ├── scheduler_time.py    # TimeScheduler: preemptive time-slice scheduler
│   │   ├── scheduler_types.py   # Task, AgentInfo, TimeSlice dataclasses
│   │   ├── statecharts.py       # 5-region state machine
│   │   ├── htn_planner.py       # HTN planner
│   │   ├── memory.py            # Agent memory (3 rings)
│   │   ├── memory_init.py       # Boot/shutdown memory lifecycle
│   │   ├── sandbox.py           # Copy-on-write isolation
│   │   ├── shell.py             # Terminal service (session management)
│   │   ├── shell_completer.py   # Tab completion for shell
│   │   ├── shell_session.py     # Shell session lifecycle (create/attach/kill)
│   │   ├── cache.py             # Multi-level cache
│   │   ├── identity.py          # Ed25519 keys + proofs
│   │   ├── api_gateway.py       # HTTP/WS API gateway
│   │   ├── ops_console.py       # Central monitoring
│   │   ├── config_loader.py     # praxis.yaml loader
│   │   ├── config_handlers.py   # Config validation + migration helpers
│   │   ├── execution_engine.py  # Step execution engine
│   │   ├── execution_plan.py    # Card→Plan compiler
│   │   ├── decomposer.py        # Card decomposer
│   │   ├── fault_tolerance.py   # Checkpoints + recovery
│   │   ├── context.py           # Context register
│   │   ├── pager.py             # Context paging
│   │   ├── pager_bridge.py      # Swapper↔Pager bridge
│   │   ├── pal_router.py        # LLM cost router
│   │   ├── stagnation.py        # Deadlock/loop detection
│   │   ├── acb.py               # Agent Control Block
│   │   ├── assembly.py          # Assembly mode
│   │   ├── service_manager.py   # Service lifecycle (systemctl analog)
│   │   ├── tool_registry_setup.py # Tool auto-discovery
│   │   ├── auth.py              # Auth service
│   │   ├── ci.py                # CI pipeline
│   │   ├── git.py               # Git operations
│   │   ├── fs.py                # Filesystem ops
│   │   ├── log.py               # Log service
│   │   ├── lsp.py               # LSP integration
│   │   ├── network.py           # HTTP client
│   │   ├── notify.py            # Notifications
│   │   ├── package_manager.py   # Package management
│   │   ├── process.py           # Process manager
│   │   ├── search.py            # Text search
│   │   ├── template.py          # Jinja2 templates
│   │   ├── todo.py              # Task queue
│   │   ├── subagent.py          # Lightweight synchronous quick-check agent
│   │   ├── transaction_area.py  # Card queue for L3A↔Cell
│   │   ├── user_session.py      # Login/session
│   │   ├── vspace.py            # Virtual project space
│   │   ├── workspace.py         # Workspace manager
│   │   ├── result_store.py      # Deterministic tool result cache (SHA256+LRU)
│   │   ├── cache_strategy.py    # Per-provider LLM prefix cache strategy
│   │   ├── tool_mode.py         # Global read/write mode switch
│   │   ├── central_security.py  # CentralSecurity — 6-gate unified check
│   │   ├── central_memory.py    # CentralMemory — R1-R4 lifecycle coordinator
│   │   ├── central_plugin.py    # CentralPlugin — plugin lifecycle manager
│   │   ├── cell_monitor.py      # CellMonitor — cell health event log
│   │   ├── observability_bus.py # ObservabilityBus — unified alert/health/metric/audit
│   │   ├── l2_shell.py          # L2 Shell command dispatch + auto-complete
│   │   ├── shell_completer.py   # Shell auto-completion engine
│   │   ├── _base.py             # Base service
│   │   ├── _pool.py             # Worker pool
│   │   ├── _term_types.py       # Terminal data types
│   │   └── _term_handlers.py    # Terminal action handlers
│   │
│   │── REMOVED: dispatch.py     # Replaced by CardRegistry
│   │── REMOVED: event_bridge.py # Merged into kernel EventBus (string API)
│   │── REMOVED: events.py       # Merged into kernel EventBus
│   │
│   ├── tools/                   # Tool implementations (~50+ files)
│   │   ├── base/                # Core tools (16 files)
│   │   ├── advanced/            # Extended tools (16 files)
│   │   ├── cell/                # Agent coordination (5 files)
│   │   └── special/             # L3 + Archive (4 files)
│   │
│   └── services/__init__.py     # Namespace marker
│
├── tests/                       # pytest test suite
│   ├── test_params_integrity.py # 17 tests — constant integrity
│   ├── test_kernel.py           # 26 tests — all kernel modules
│   ├── test_kernel_extended.py  # 21 tests — reputation, lock, registry, skill, swapper
│   ├── test_identity.py         # 13 tests — Ed25519 keygen, proof, trust chain
│   ├── test_memory_sandbox.py   # 14 tests — memory rings, sandbox isolation
│   ├── test_integration.py      # 5 tests — syscall, registry, VFS, emit_signal
│   ├── test_services.py         # 13 tests — service layer (needs mock fix)
│   ├── test_praxis_conventions.py  # 1 test — hardcoded constant audit
│   └── ... (total ~95 passing)
│
├── docs/
│   └── design/
│       └── praxis-architecture-actual.md  # This document
│
└── .github/workflows/ci.yml     # CI: ruff → mypy → pytest × 3 Python versions → build
```

---

## 15. Fault Tolerance & Checkpoint Recovery

```mermaid
flowchart TB
    subgraph CP["Checkpoint System (services/fault_tolerance.py)"]
        SAVE["save_checkpoint()\nbefore each step\n→ JSON to disk\n→ in-memory dict"]
        RESTORE["restore_checkpoint()\non crash recovery\n→ load from disk\n→ resume from last step"]
        DONE["mark_done()\nphase complete\n→ delete checkpoint"]
        MONITOR["_monitor_loop()\nevery 5s\n→ check heartbeats\n→ detect crashes"]
    end

    subgraph Flow["Card Execution with Checkpoints"]
        P1["Phase 1: investigate"] -->|"save_checkpoint before each step"| S1["Step 1: think"]
        S1 -->|"step result"| S2["Step 2: read_file"]
        S2 -->|"save_checkpoint"| P2["Phase 2: modify"]
        P2 -->|"mark_done(agent)"| END["Card Complete"]
    end

    subgraph Recovery["Crash Recovery"]
        CRASH["Heartbeat lost >30s"] -->|"_check_heartbeats()"| DETECT["status = crashed"]
        DETECT -->|"on_agent_crash()"| RESTORE
        RESTORE -->|"resume from checkpoint"| P1
    end

    subgraph Timeline["Crash Timeline (from Agent OS spec §5.1)"]
        T0["T+0: Heartbeat lost"] --> T15["T+15s: Mark UNRESPONSIVE"]
        T15 --> T30["T+30s: Mark CRASHED → recovery"]
        T30 --> REC["restore checkpoint → restart"]
    end

    subgraph Zombie["Zombie Reaper (kernel/process.py)"]
        ZMON["Background daemon thread\nevery 60s"] --> ZCHECK["Check ZOMBIE processes\nolder than 300s"]
        ZCHECK --> ZREAP["Reap → remove from PID table"]
        ZCHECK --> ZCAP["Cap: >500 processes →\nreap oldest STOPPED/ZOMBIE"]
    end

    subgraph AutoMode["Autonomous Mode (§5.3)"]
        L3DOWN["L3 unreachable"] --> AUTO["_autonomous_mode = True"]
        AUTO -->|"current tasks continue"| RESTRICT["Restrictions:\n- New intents blocked\n- Cross-cell blocked\n- Cross-review allowed\n- Tasks continue"]
        L3UP["L3 restored"] -->|"_autonomous_mode = False"| NORMAL["Normal operation"]
    end
```

### Checkpoint in Execution Plan

Each step boundary saves a checkpoint:

```python
# execution_plan.py
for ps in phase_steps:
    save_checkpoint(agent_id=ps.agent, 
                    task_id=f"{card.id}:{ps.step_id}",
                    progress={"phase": ps.phase, "step": ps.step_id})
    r = execute_step(ps, timeout)
    # ...
mark_done(agent_id)  # phase complete
```

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `HEARTBEAT_TIMEOUT` | 15s | Time before agent marked UNRESPONSIVE |
| `CRASH_TIMEOUT` | 30s | Time before agent marked CRASHED |
| `FAULT_CHECK_INTERVAL` | 5s | Background monitor check interval |
| `FAULT_RETRY_INTERVAL` | 1s | Retry delay before recovery |
| `TOOL_HANDLER_TIMEOUT` | 60s | Max seconds per tool handler in tool_use() |
| Zombie reap age | 300s | ZOMBIE processes older than 5min are reaped |
| Process cap | 500 | Max processes before GC reaps oldest |

### Emergency Stop & Rollback

| API Endpoint | Description |
|-------------|-------------|
| `POST /api/cell/stop {cell_id}` | Set emergency flag, pause all agents, block new cards |
| `POST /api/cell/resume {cell_id}` | Clear flag, resume agents |
| `POST /api/card/rollback {card_id, cell_id}` | Restore checkpoint + discard sandbox changes |

Rollback restores from `fault_tolerance` checkpoint and discards `pending/staged` sandbox files. Already-`flushed` files are not reverted — full git-level rollback is a future enhancement.


## 16. Settings Center

```mermaid
flowchart TB
    subgraph Center["Settings Center (services/settings_center.py)"]
        L1["L1 — Default\nkernel/params.py\n(read-only factory defaults)"]
        L2["L2 — Config\npraxis.yaml\n(boot-time, loaded via load_l2())"]
        L3["L3 — Runtime\n.praxis_settings.json\n(API-written, persisted)"]
        MERGE["get(key): L3 > L2 > L1\nset(key, val): writes L3 only"]
    end

    subgraph Consumers["Integrated Consumers"]
        AG["approval_gate.py\n_get_threshold()\n→ get_center().get_int()"]
        API["api_gateway.py\nGET /api/settings → all()\nPOST /api/settings → set_many()"]
        BOOT["boot.py\n→ load_config()\n→ get_center().load_l2()"]
    end

    BOOT -->|"boot"| L2
    L1 --> MERGE
    L2 --> MERGE
    L3 --> MERGE
    MERGE --> AG
    MERGE --> API
    API -->|"POST"| L3
```

### Three-Layer Priority

| Layer | Source | Persisted | Effect | Priority |
|-------|--------|-----------|--------|----------|
| L1 — Default | `params.py` L1 map | No (code) | Compile-time | Lowest |
| L2 — Config | `praxis.yaml` | Yes (file) | Boot-time | Medium |
| L3 — Runtime | API (`POST /api/settings`) | Yes (JSON) | **Immediate** | **Highest** |

### Runtime-Overridable Keys

| Key | Default | Description |
|-----|---------|-------------|
| `approval.danger_threshold` | 3 | Tools with danger >= this require human approval |
| `memory.working_budget` | 8192 | Ring 1 token budget |
| `memory.short_budget` | 32768 | Ring 2 token budget |
| `memory.long_budget` | 131072 | Ring 3 token budget |
| `scout.max_total` | 16 | Scout pool capacity |
| `scout.max_per_agent` | 4 | Scouts per agent |
| `terminal.max_workers` | 4 | AgentTerminal worker threads |
| `scheduler.default_quantum` | 15.0 | Time slice in seconds |
| `scheduler.max_preempt` | 60.0 | Max execution before force preempt |
| `cache.max_entries` | 500 | File cache entry limit |
| `gatechain.risk_warn_threshold` | 6.0 | G3 risk score threshold |
| `gatechain.repeat_threshold` | 5 | G5 repeat detection |
| `llm.max_tokens` | 2048 | LLM output token limit |
| `llm.temperature` | 0.3 | LLM temperature |
| `llm.reasoning_effort` | "none" | OpenAI o-series reasoning (none/low/medium/high) |
| `llm.thinking_budget` | 0 | Anthropic extended thinking (0=off) |

### API

```bash
# Read all (three layers merged)
curl http://localhost:8080/api/settings

# Override a setting (immediate, persists to .praxis_settings.json)
curl -X POST http://localhost:8080/api/settings \
  -H "Content-Type: application/json" \
  -d '{"approval.danger_threshold": 5}'

# Reset an override
curl -X POST http://localhost:8080/api/settings \
  -d '{"approval.danger_threshold": null}'
```


## 17. Observability & Counters

```mermaid
flowchart TB
    subgraph Hooks["LLM Lifecycle Hooks (services/llm.py)"]
        PRE["@on_llm_call('pre')\nbefore generate()\nlogging, audit, prompt injection"]
        POST["@on_llm_call('post')\nafter generate()\ntoken counting, cost tracking"]
        LLM["LLMEngine.generate()"]
        PRE --> LLM --> POST
    end

    subgraph Counter["Cell Counter (services/counter.py)"]
        TOKENS["record_token()\ninput/output/cache_hit/cache_miss\nper-agent, with timestamps"]
        TOOLS["record_tool()\ntool name + success/failure\nper-agent"]
        LOOPS["record_loop()\nturns + steps + elapsed\nper AgentLoop run"]
    end

    subgraph API["TUI-ready Endpoints"]
        T1["GET /api/tokens?window=60\n→ tokens_per_min real-time rate\n→ by_agent breakdown"]
        T2["GET /api/tools\n→ calls/success/failure per tool\n→ avg_elapsed per tool"]
        T3["GET /api/loops\n→ avg_turns_per_loop\n→ avg_steps_per_turn"]
    end

    POST -->|"auto-wired hook"| TOKENS
    TOOL_EXEC["tool_spec.py\nexecute_tool_spec()"] -->|"post-exec"| TOOLS
    AGENT_LOOP["agent_loop.py\nrun()"] -->|"post-run"| LOOPS
    TOKENS --> T1
    TOOLS --> T2
    LOOPS --> T3
```

### Auto-Wired Integration

| Counter | Trigger | Integration Point |
|---------|---------|-------------------|
| Token | Every LLM API call | `llm.py:@on_llm_call("post")` — no manual calls needed |
| Tool call | Every tool execution | `tool_spec.py:execute_tool_spec()` — auto-recorded |
| AgentLoop turn | Every `think` action | `agent_loop.py:run()` — auto-recorded |

### LLM Hook Decorator

```python
from services.llm import on_llm_call

@on_llm_call("pre")
def log_prompt(prompt, system, max_tokens, user_id, **kwargs):
    logger.info("LLM call: user=%s tokens=%d", user_id, max_tokens)

@on_llm_call("post")
def log_result(result, prompt="", **kwargs):
    logger.info("LLM done: %d tokens", result.get("tokens", 0))
```

### Real-Time Dashboard Data

```bash
# Token consumption rate (last 60s) — TUI polls every 5s
GET /api/tokens?window=60
→ {"rate": {"tokens_per_min": 45230, "calls_in_window": 8,
    "by_agent": {"agent-reader": {"tokens_per_min": 28000}}}}

# Tool call statistics
GET /api/tools
→ {"agent-reader": {"total": 42,
    "by_tool": {"read_file": {"calls": 20, "success": 20, "avg_elapsed": 0.02}}}}

# AgentLoop statistics
GET /api/loops
→ {"agent-reader": {"total": 12, "avg_turns_per_loop": 3.2, "avg_elapsed_per_loop": 8.5}}
```


## 18. Security Architecture

```mermaid
flowchart LR
    subgraph OuterRing["Outer Ring — Constitution"]
        CONST_RULES["Constitution Rules\n(.nomos-rules.md)\nTerritory / Audit / Scout"]
    end

    subgraph MiddleRing["Middle Ring — GateChain G1-G5"]
        G1["G1: Tool Whitelist"]
        G2["G2: Identity (Ed25519)"]
        G3["G3: Territory + Risk"]
        G4["G4: Escalation (L3)"]
        G5["G5: Composite Judgment\n(Reputation + History)"]
    end

    subgraph InnerRing["Inner Ring — Execution"]
        TOOL["Tool Execution"]
        SANDBOX["Sandbox\n(Copy-on-Write)"]
        AUDIT["Audit Trail\n(Syscall Log)"]
        FINGERPRINT["Fingerprint Chain\n(HMAC-SHA256)"]
    end

    TOOL --> AUDIT
    TOOL --> FINGERPRINT
    SANDBOX --> AUDIT
```

---

## 19. Data Flow: Intent → Execution

```mermaid
sequenceDiagram
    participant H as Human
    participant L3A as L3A (Agent)
    participant REG as CardRegistry
    participant CELL as Cell
    participant PLAN as ExecutionPlan
    participant MEM as Memory (3-ring)
    participant AGT as AgentTerminal
    participant RT as AgentRuntime
    participant TOOL as Tool

    H->>L3A: "fix bug in login"
    L3A->>L3A: parse intent (LLM + rule) → TaskCard
    L3A->>REG: submit(card)
    REG->>CELL: dispatch(card_id)
    CELL->>PLAN: execute_card(card)

    loop for each phase
        loop for each step
            PLAN->>AGT: dispatch (TerminalCard)
            AGT->>RT: tick(Action)

            RT->>RT: 1. constitution.check()
            RT->>RT: 2. gatechain.check() (G1-G5)
            RT->>RT: 3. memory.build_context() → system prompt
            RT->>RT: 4. allocator.alloc()
            RT->>RT: 5. limiter.check()
            RT->>RT: 6. lock.acquire()
            RT->>TOOL: 7. execute_tool_spec()
            TOOL-->>RT: result
            RT->>MEM: 8. memory.remember(Ring 1)
            MEM-->>RT: pressure check
            RT->>RT: 9. lock.release()
            RT-->>AGT: CardResult
            AGT-->>PLAN: step result
        end

        alt memory.pressure() == "high"
            PLAN->>MEM: snapshot context → compact → restore
        end
    end

    PLAN-->>CELL: aggregated result
    CELL->>REG: complete(card_id, result)
    REG-->>L3A: status
    L3A-->>H: result summary
```


## 20. Central Control Systems (Overview)

The Agent OS is governed by ten central control systems ("十大中心主控系统"):

```mermaid
flowchart TB
    subgraph Centers["Ten Central Control Systems"]
        CC["① CentralController\nl3.py\nIntent Lifecycle\nParse → Queue → Dispatch → Complete"]
        CS["② CentralScheduler\nscheduler.py\n5D Scheduling\nRoute/Pool/Time/Rate/Scope"]
        OB["③ ObservabilityBus\nobservability_bus.py\nUnified Observability\nAlert/Health/Metric/Audit"]
        R4["④ R4Agent\nr4_agent.py\nArchive Management\nConsistency + Lean Cases"]
        CM["⑤ CellMonitor\ncell_monitor.py\nCell Health Monitor\nRing Buffer Event Log"]
        L3B["⑥ L3B\nl3b.py\nCross-Cell Coordinator\nRouting + Conflict Arbitration"]
        CSEC["⑦ CentralSecurity\ncentral_security.py\nUnified Security Engine\nConstitution + GateChain + Auth\n+ ToolMode + Rate + Clearance"]
        CMEM["⑧ CentralMemory\ncentral_memory.py\nMemory Lifecycle\nRemember/Recall/Compact/Archive\nAcross Ring 1-4"]
        CPLUG["⑨ CentralPlugin\ncentral_plugin.py\nPlugin Lifecycle\nTool/MCP/Service\nInstall/Remove/List"]
        CCOL["⑩ CentralCollector\ncentral_collector.py\nToken Aggregation\nCross-Cell Usage Tracking"]
    end

    subgraph Managed["Managed Subsystems"]
        CR["CardRegistry"]
        SCHED["TimeScheduler\nRateScheduler\nRequestPool"]
        HEALTH["Health\nCounter\nOpsConsole"]
        MEM["Memory Rings 1-4"]
        AGENTS["AgentTerminal\nScoutPool"]
        TOOLS["ToolRegistry\nMCPBridge"]
        SEC["Constitution\nGateChain\nAuth\nToolMode"]
    end

    CC --> CR
    CS --> SCHED
    OB --> HEALTH
    R4 --> MEM
    CM --> AGENTS
    L3B --> CC
    CSEC --> SEC
    CMEM --> MEM
    CPLUG --> TOOLS
```

### Center Details

| # | Center | File | Primary Role | Subsystems Coordinated |
|---|--------|------|-------------|----------------------|
| 1 | **CentralController** | `l3.py` | Intent lifecycle controller | CardRegistry, L3A, Dispatcher |
| 2 | **CentralScheduler** | `scheduler.py` | 5D scheduling matrix | RouteScheduler, RateScheduler, TimeScheduler, RequestPool, ScopeScheduler |
| 3 | **ObservabilityBus** | `observability_bus.py` | Unified observability | OpsConsole, Health, Counter, Audit |
| 4 | **R4Agent** | `r4_agent.py` | Background archive management | Memory Ring 4, ArchiveOrchestrator |
| 5 | **CellMonitor** | `cell_monitor.py` | Cell health event log | AgentTerminal, ScoutPool |
| 6 | **L3B** | `l3b.py` | Cross-cell routing & arbitration | CentralController, Cell |
| 7 | **CentralSecurity** | `central_security.py` | 6-gate unified security check | Constitution, GateChain, Auth, ToolMode, RateLimiter |
| 8 | **CentralMemory** | `central_memory.py` | 4-ring memory lifecycle | Memory, MemoryRing, MemoryQuality, R4Agent, ArchiveOrchestrator |
| 9 | **CentralPlugin** | `central_plugin.py` | Plugin lifecycle management | ToolSpec, MCPBridge, BaseService |
| 10 | **CentralCollector** | `central_collector.py` | Cross-Cell token aggregation | Token usage events, per-Cell summaries |

---

## 21. OpenCoder Bridge (TBD)

> Reserved for OpenCoder IDE integration specification.

---

## 22. Multi-Cell Federation (TBD)

> Reserved for multi-Cell deployment, cross-Cell Card routing, and Cell mesh protocol specification.

---

## Appendix A: Convention & Deliberation Protocol

The Assembly/Convention protocol enables multi-agent deliberation before execution. L3A produces an IssueCard, broadcasts it to all Peer Agents, who respond by territory, propose supplementary issues, and participate in sequential cross-examination.

### Flow

```
L3A → IssueCard 
  → Cell.execute_card() detects IssueCard → Cell.convene()
  → ConventionProtocol.start() → broadcasts CONVENE to all agents
  → Each Agent answers issues by territory match
  → Agents propose supplementary issues (PROPOSE_ISSUE)
  → Sequential cross-examination (CONVENTION_MAX_ROUNDS=2 rounds)
  → ConventionProtocol.close() → CacheDocument + Archive (Ring 4)
  → converge() → rule/LLM summary
  → to_execution_card() → Card → CardRegistry
```

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `CONVENE` | L3A → All | Start deliberation |
| `CROSS_EXAMINE` | Agent → Agent | Cross-examination |
| `REBUT` | Agent → All | Rebuttal |
| `PROPOSE_ISSUE` | Agent → Table | Propose new issue |
| `CONVENE_CLOSE` | Convention → All | Close deliberation |

### Key Data Structures

| Component | File | Description |
|-----------|------|-------------|
| `IssueStatus` | `issue.py` | PENDING / ANSWERED / SUPPLEMENTED / RESOLVED / WITHDRAWN |
| `IssueCard` | `issue.py` | Agenda card with multiple IssueItems, status lifecycle |
| `IssueTable` | `issue.py` | Central registry — L3A/Agents operate on the same table |
| `CacheDocument` | `cache_doc.py` | Buffer-addressed meeting document (buffer_id, Archive ref) |
| `ConventionTranscript` | `convention.py` | Per-round speaker statements |
| `ConventionProtocol` | `convention.py` | Engine: rounds, speaker order, document builder |
| `Convergence` | `convergence.py` | L3A summary (LLM or rule-based) → ExecutionCard |

### Converged → Execution Card

```python
from services.convergence import converge, to_execution_card

result = converge(issue_card_id)          # LLM/rule summary
exec_card = to_execution_card(issue_card, summary)  # Card with phases/steps
CardRegistry.submit(intent=exec_card.intent, ...)
```


## Appendix B: Credential Vault

LLM API keys are encrypted at rest using AES-GCM and loaded into memory at boot.

### Architecture

```mermaid
flowchart LR
    subgraph Storage["Disk (encrypted)"]
        FILE["credential_vault.enc\nAES-GCM ciphertext"]
    end
    subgraph Memory["Memory (decrypted)"]
        DICT["dict[provider][key_name] = value"]
    end
    subgraph Fallback["Env Fallback"]
        ENV["OPENAI_API_KEY\nANTHROPIC_API_KEY\n..."]
    end

    FILE -->|"boot: init_vault()"| DICT
    DICT -->|"get_credential()"| LLM["LLM Providers"]
    ENV -->|"fallback"| LLM
    YAML["praxis.yaml → credentials:"] -->|"cfg_credentials()"| DICT
    API["POST /api/credentials"] -->|"set_credential()"| DICT
    DICT -->|"export (no values)"| API_GW["GET /api/credentials"]
```

### Key Features

| Feature | Implementation |
|---------|---------------|
| Encryption | AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM` |
| Key Derivation | SHA256(PRAXIS_DATA_DIR + hostname + "praxis-v1") |
| Storage Path | `{PRAXIS_DATA_DIR}/credential_vault.enc` |
| Env Fallback | `get_credential("openai", "api_key", env_fallback="OPENAI_API_KEY")` |
| Runtime Update | `POST /api/credentials  {"provider": "openai", "key": "api_key", "value": "sk-..."}` |
| YAML Import | `praxis.yaml → credentials: { openai: { api_key: "..." } }` |


## Appendix C: Extensibility Architecture

The codebase uses registry patterns to allow external code to add functionality without modifying core files.

### Boot Step Registry

```python
from services.boot import register_boot_step

def my_init() -> dict:
    # Custom initialization
    return {"success": True}

register_boot_step("my_custom_init", my_init, depends_on=["init_services"])
```

Dependencies are resolved via topological sort at boot time.

### API Route Registry

```python
# Code registration
gateway.register_route("GET", "/api/v1/my/endpoint", my_handler, "My endpoint")

# YAML configuration (praxis.yaml)
# api_routes:
#   - method: GET
#     path: /api/v1/external/doc
#     handler: "services.cache_doc:get_store.get_content"
#     description: "Get document"
```

Handler strings use dot-path resolution: `"module.path:attr.subattr"` → `import module.path; obj = attr.subattr`.

### Tool Handler Registry

```python
from services._term_handlers import register_func_handler

def my_handler(term, card, phases):
    return "output", [], True

register_func_handler("my_tool", my_handler)
```

### Rollback Strategy Registry

```python
from services.execution_engine import register_rollback

def undo_my_tool(step, plan, executor):
    path = step.params.get("path", "")
    if path:
        os.remove(path)

register_rollback("my_tool", undo_my_tool)
```

### Config Handler Registry

```python
from services.config_loader import register_config_handler

def cfg_my_section(data, settings, results):
    # Apply config section
    results["my_section"] = True

register_config_handler("my_section", cfg_my_section)
```

### Summary of Extension Points

| Registry | File | API | Purpose |
|----------|------|-----|---------|
| Boot steps | `boot.py` | `register_boot_step()` | Custom initialization |
| API routes | `api_gateway.py` | `register_route()` + YAML | Custom HTTP endpoints |
| Tool handlers | `_term_handlers.py` | `register_func_handler()` | Custom agent tools |
| Rollback | `execution_engine.py` | `register_rollback()` | Custom undo logic |
| Config | `config_loader.py` | `register_config_handler()` | Custom YAML sections |
| HTN methods | `htn_planner.py` | `register_method()` | Custom task decomposition |
| Card detectors | `card_builder.py` | `register_detector()` | Custom intent builders |
| LLM lifecycle | `llm.py` | `@on_llm_call` | Pre/post LLM hooks |


## 23. Config-Driven Architecture

The Agent OS uses YAML-driven configuration for three key subsystems, following the same pattern:

```mermaid
flowchart LR
    subgraph YAML["praxis.yaml"]
        PROMPTS["prompts:\n  agent_loop.system:\n  l3a.parse_system:"]
        COMMANDS["commands:\n  mode:\n  connect:\n    args:"]
        CACHE["llm:\n  cache:\n    openai:\n    anthropic:"]
    end

    subgraph Code["Python Code"]
        PP["kernel/prompts.py\n_DEFAULTS + _overrides"]
        PC["kernel/commands.py\n_DEFAULTS + _overrides"]

        PS["services/cache_strategy.py\nload_cache_config(cfg)\n→ ConfigCacheStrategy"]
    end

    subgraph Resolution["Resolution Order"]
        R1["Override > Default\n(deep merge)"]
        R2["Per-provider > defaults"]
    end

    PROMPTS --> PP
    COMMANDS --> PC
    CACHE --> PS
    PP --> R1
    PC --> R1
    PS --> R2
```

### Prompt Templates (`praxis.yaml → prompts:`)

```yaml
prompts:
  agent_loop.system: "You are an agent. Complete: {task}"
  agent_loop.system.reader: "You are the reader agent."
  scout.system: "Custom scout prompt..."
```

Keys: 17 built-in (agent_loop, l3a, convention, verifier, review, agent_terminal, convergence, llm).
Resolution: `get_prompt(key) → override > built-in > passed default`.

### Shell Commands (`praxis.yaml → commands:`)

```yaml
commands:
  mode:
    help: "Switch mode"
    aliases: ["m"]
  connect:
    args:
      - name: agent_id
        optional: false
```

Resolution: `get_command(name) → merged {**default, **override}`.
Handler registration in code: `register_command(name, handler_fn)`.

### Cache Strategies (`praxis.yaml → llm.cache`)

```yaml
llm:
  cache:
    defaults:
      optimize_prompt: true
      forward_user_id: false
      anthropic_format: false
    openai:
      optimize_prompt: true
      forward_user_id: true
    anthropic:
      optimize_prompt: false
      anthropic_format: true
    ollama:
      optimize_prompt: false
```

The `ConfigCacheStrategy` class reads these flags and applies them dynamically — no per-provider Python classes needed.
New providers are added by simply adding a YAML section; no code change required.
Plugins can still `register_strategy("custom", CustomStrategy())` for special cases.

---

## 24. ResultStore & Cache Architecture

### ResultStore (`services/result_store.py`)

AtomCode-style deterministic tool result cache:

```mermaid
flowchart LR
    subgraph Execute["Tool Execution"]
        FP["ResultStore.fingerprint(tool_name, args)\n→ SHA256(tool_name + canonical_json(args))[:16]"]
        FP --> CHECK{"ResultStore.get(fp)?"}
        CHECK -->|"HIT"| RETURN["Return cached result\n(skip execution)"]
        CHECK -->|"MISS"| RUN["execute_tool_spec()"]
        RUN --> STORE["ResultStore.set(fp, result)\nLRU eviction at max_entries"]
        RUN --> INVAL["write tool → invalidate_for_tool()\nclear matching path entries"]
    end
```

| Feature | Detail |
|---------|--------|
| Key | SHA256(tool_name + canonical JSON args) — 16 hex chars |
| Eviction | LRU via `OrderedDict.move_to_end()`, `popitem(last=False)` |
| TTL | `RESULT_STORE_TTL` (default 300s) |
| Write-invalidation | `invalidate_for_tool()` clears entries matching write tool path |
| Integration | Wired into `execute_tool_spec()` — automatic for all tools |

### Cache Strategy Per-Provider (`services/cache_strategy.py`)

Single `ConfigCacheStrategy` class driven by YAML config, not an ABC hierarchy:

| Provider | optimize_prompt | forward_user_id | anthropic_format |
|----------|----------------|-----------------|------------------|
| OpenAI | Yes → `[System]/[Task]` | Yes | No |
| DeepSeek | Yes | Yes (KV isolation key) | No |
| Anthropic | No (uses top-level system field) | Yes | Yes → cache_control injection |
| Ollama | No | No | No |
| Unknown | Yes (falls back to defaults) | No | No |

---

## Appendix D: Ten Central Control Systems (Complete)

The Agent OS is governed by ten central control systems:

| # | Center | File | Role | Key API |
|---|--------|------|------|---------|
| 1 | CentralController | `l3.py` | Intent lifecycle | `process_intent()` |
| 2 | CentralScheduler | `scheduler.py` | 5D scheduling | `evaluate_all()` |
| 3 | ObservabilityBus | `observability_bus.py` | Unified observability | `observe(kind, source, data)` |
| 4 | R4Agent | `r4_agent.py` | Archive management | `tick()` |
| 5 | CellMonitor | `cell_monitor.py` | Cell health | `register_cell()`, `report_agent()` |
| 6 | L3B | `l3b.py` | Cross-cell routing | `route(card_id, cell_a, cell_b)` |
| 7 | **CentralSecurity** | `central_security.py` | 6-gate unified check | `check_all(action, agent_id)` |
| 8 | **CentralMemory** | `central_memory.py` | R1-R4 lifecycle | `remember()`, `recall()`, `compact()` |
| 9 | **CentralPlugin** | `central_plugin.py` | Plugin lifecycle | `install_tool_plugin()`, `list_plugins()` |
| 10 | **CentralCollector** | `central_collector.py` | Cross-Cell token aggregation | `collect(agent_id, tokens)` — listens to `TOKEN_USAGE` events |
