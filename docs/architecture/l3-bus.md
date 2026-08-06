# L3 — Bus (message bus + observability + causal recording)

How the cell layer moves messages, records decisions, and emits telemetry.
One transport (kernel IPC), one protocol layer (20+ message types), and a
family of purpose-built buses for monitoring, webhooks, and — above all —
the causal reference channel that turns every agent decision into
training-grade data.

## Layered view

```mermaid
flowchart TB
    subgraph L1["L1 Kernel transport"]
        EVT["EventBus (async signals)"]
        LOCK["ipc.LockBus (in-process channel delivery)"]
        PROC["ProcessTable / threads"]
    end
    subgraph L3["L3 Protocol + buses"]
        IPC["ipc.py: MessageType / routing matrix / cross-cell"]
        RC["ReferenceChannel (JSONL + SHA-256)"]
        MON["MonitorBus + MessageGate"]
        OBS["ObservabilityBus (alerts+health+metrics+audit)"]
        LOG["LogBus (rotation/query/export)"]
        TASK["TaskBus (webhook dispatch)"]
        COMM["CommMonitor (traffic aggregation)"]
        L3B["L3BBus (composite-to-composite)"]
    end
    subgraph CONSUMERS["Consumers"]
        PIPELINE["tool_pipeline gate decisions"]
        CARD["card_registry lifecycle"]
        SEQ["sequence_monitor anomaly flags"]
        FRONT["L2 Shell / API / SSE / WS"]
        TRAIN["training pipeline (RLHF / DPO / QLoRA)"]
    end
    IPC --> LOCK
    EVT -.->|emitted from any layer| CONSUMERS
    PIPELINE --> RC
    CARD --> RC
    SEQ --> RC
    RC --> TRAIN
    MON --> FRONT
    OBS --> FRONT
    LOG --> FRONT
    TASK -->|webhook POST| WEBHOOK["external endpoints"]
    COMM --> FRONT
    L3B -->|chain forwarding| L3B
```

## ReferenceChannel — the causal recorder (`reference_channel.py`)

Pure observability, zero effect on execution: async writes, no
backpressure, no blocking. Every event is a self-contained JSON line with a
SHA-256 content hash — provenance-complete, suitable for downstream
training pipelines. The design references the NOMOS Reference Channel.

| Property | Value |
|----------|-------|
| Buffer | fixed-size ring (bounds memory; full buffer flushes immediately, never drops) |
| Flush | background daemon thread every `flush_interval`; failure re-queues events |
| Integrity | `sha256` per record (truncated to `RC_SHA256_TRUNC`) |
| API | `get_rc().event(type, data)` — O(1) append from any component |

### Event types

| Type | Source | Payload highlights |
|------|--------|--------------------|
| `tool_call` | tool_pipeline | allowed, gate, reason, **predicted_success**, deviation, card_scope |
| `card_lifecycle` | card_registry | intent, state, nature/size, error, **predicted_state**, deviation |
| `gatechain` | gatechain | per-gate decision steps |
| `human_correction` | L2 Shell / API | field, old/new preview, reason (CORRECT signals) |
| `convention` | convention | outcome, participant count, summary |
| `anomaly` | sequence_monitor | detection payload |

### The causal triple

The training-value core is the `{predicted, actual, deviation}` triple:

```
predicted_success=true  + allowed=false → false_positive_expectation
predicted_success=false + allowed=true  → false_negative_expectation
predicted_state=completed + state=failed → completion_mismatch
```

Aggregated across many calls these become negative-training-signal
datasets — the governance layer records *why* the model was wrong, which
is precisely the "儿童机器" (child machine) causal data that later
weight-level training consumes. The harness `governed/semi/minimal` modes
never skip this recording: it is part of the safety bottom line.

Export: `export(limit, offset, event_type)` (pure query), `count(type)`,
`stats()` (buffered / flusher alive).

## IPC protocol layer (`ipc.py`)

Transport lives in L1 (`kernel/ipc.LockBus`); `l3/bus/ipc.py` is the
protocol: `MessageType` + routing matrix + cross-cell routing (Agent OS
spec §2). 20+ message types across 7 categories:

| Direction | Message types |
|-----------|---------------|
| L3 → Agent | `task.assign`, `task.cancel`, `review.result` |
| Agent → L3 | `task.accept`, `task.done`, `task.error`, `dispute.raise`, `issue.proposal`, `scout.request` |
| Agent ↔ Agent | `review.request`, `review.response`, `territory.query`, `agent.message`, `agent.broadcast` |
| Scout → Agent | `scout.report`, `scout.progress` |
| System | `heartbeat`, `constitution.update`, `cell.join`, `cell.leave`, `cell.restart`, `scout.timeout` |
| Direct | `direct.session_start`, `direct.session_end`, `direct.message` |

Communication is constrained by an allow/deny matrix — the protocol layer
is where agent-to-agent trust is expressed.

## Purpose-built buses

| Bus | Module | Role |
|-----|--------|------|
| MonitorBus | `monitor_bus.py` | unified typed event stream (`kernel.*` / `network.*` / `service.*` / `task.*`), JSONL persistence, ring rehydrated on startup, streaming |
| MessageGate | `message_gate.py` | dependency-aware policy engine over MonitorBus: `allow` / `block` / `mute` / `hold` / `redirect`, with dependency chains + hold timeout |
| ObservabilityBus | `observability_bus.py` | single `observe()` facade wrapping ops_console (alerts) + health + counter (metrics) + audit (syscall log) |
| LogBus | `log.py` | OS-level logging: levels, size-based rotation, time-range query, JSON export, service tagging; integrates with the kernel event bus |
| TaskBus | `task_bus.py` | webhook dispatch on card completion: subscriber filters, exponential backoff (3 attempts: 1s → 4s → 10s), non-blocking, `webhooks:` config |
| CommMonitor | `comm_monitor.py` | traffic aggregation across IPC/cell-mailbox/event history: message counts, latency samples, trace IDs, heartbeats, health probes |
| L3BBus | `l3b_bus.py` + `l3b_message_pool.py` | composite-to-composite chain + hop-by-hop forwarding (`CARD_FORWARD` / `RESULT_BACK` / `STATUS_CHECK` / `BACKPRESSURE`), one mailbox per composite |

## Relation

- `l1-kernel.md` §EventBus: transport primitives; L3 buses ride on the
  same kernel event bus for cross-service log collection and signals.
- `l3-routing.md` §Message gate/pool: L3B composites and message pooling
  are covered there for routing; this document covers the buses
  themselves.
- `l3-tools.md` §pipeline: every gate decision lands in the Reference
  Channel; the harness-mode bottom line guarantees recording in all modes.
- `cross-cutting.md` §events: SSE `/api/events` + WS stream the kernel
  event bus outward to frontends.
