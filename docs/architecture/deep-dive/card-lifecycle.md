# Card Lifecycle

> **Sources:** `l3/card_registry.py`, `l3/card_gate.py`, `l3/card_unified.py`, `l3/pending_queue.py`

## State Machine

```mermaid
stateDiagram-v2
    [*] --> QUEUED: registry.submit()
    QUEUED --> DISPATCHED: registry.dispatch()
    DISPATCHED --> RUNNING: cell.execute_card()
    RUNNING --> DISPATCHED: decompose -> sub-cards
    RUNNING --> VERIFYING: step complete
    VERIFYING --> RUNNING: verify fail -> retry
    VERIFYING --> DONE: all steps + verify pass
    DONE --> [*]: registry.complete()
    RUNNING --> FAILED: unrecoverable
    FAILED --> [*]
    QUEUED --> CANCELLED: registry.cancel()
    DISPATCHED --> HELD: CardGate
    HELD --> PENDING: pending_queue.enqueue()
    PENDING --> DISPATCHED: human approves
    PENDING --> CANCELLED: human rejects
```

## Dual-Layer Card Queue

### 1. Dispatch Queue (`CardRegistry._queue`)

Priority-sorted list of card IDs waiting for Cell dispatch.

### 2. CardGate + PendingQueue

Human/convention approval queue for cards requiring review.

```mermaid
flowchart TB
    SUBMIT["registry.submit()"] --> CLASSIFY["classify card:
    small | medium | large | disputed"]
    CLASSIFY --> SMEVAL{"size evaluation"}
    SMEVAL -->|"small (<50 items)"| AUTO["auto_approve"]
    SMEVAL -->|"medium (50-200)"| AUTO2["auto_approve (notify L3A)"]
    SMEVAL -->|"large (>200)"| HOLD["-> PendingQueue"]
    SMEVAL -->|"disputed"| HOLD
    AUTO --> DISPATCH["_dispatcher_loop() every 1s"]
    AUTO2 --> DISPATCH
    HOLD --> ENQUEUE["enqueue(card_id, size)"]
    ENQUEUE --> APPROVE["approve() -> restore_card()"]
    ENQUEUE --> REJECT["reject() -> remove from queue"]
    ENQUEUE --> ESCALATE["escalate() -> convene convention"]
    APPROVE --> DISPATCH
```

## Card Record

```python
class CardRecord:
    card_id: str
    intent: str
    domain: str
    status: CardState     # QUEUED | DISPATCHED | RUNNING | ...
    priority: int         # 1-10
    approval_status: str  # pending | auto_approved | human_approved | rejected | escalated
    approval_size: str    # small | medium | large | disputed
    phases: list[Phase]
```

## PendingQueue

Persistent queue for cards awaiting human decisions.

| Method | Description |
|--------|-------------|
| `enqueue(card_id, intent, domain, size, priority)` | Add to pending |
| `approve(msg_id, response)` | Approve, restore in CardRegistry |
| `reject(msg_id, response)` | Reject, mark REJECTED |
| `escalate(msg_id)` | Escalate to convention |
| `list(status, limit)` | Query by status |
| `set_priority(msg_id, priority)` | Adjust priority |

## Approval Trail

Each card records its approval history:

```
approval_status: pending | auto_approved | human_approved | rejected | escalated
approval_size:   small | medium | large | disputed
approval_at:     ISO timestamp
approval_by:     agent_id or "auto"
```

## Card Types

Registered via `card_unified.py`. Each card type defines phases, steps, and verification chain.

```python
card = CardUnified(nature="execution", priority=5)
card.add_phase(name="investigate", mode="parallel", agents=["reader", "scout"])
card.add_task(phase_name="investigate", action="read_file", target="src/main.py")
```
