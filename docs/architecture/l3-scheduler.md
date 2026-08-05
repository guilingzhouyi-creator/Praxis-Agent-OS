# L3 — Scheduler (5D matrix)

The CPU scheduler of the agent SoC: 11 files in `src/l3/scheduler/` route,
time-slice, rate-limit, budget, and pool agent work — plus loop/sequence
safety layers and thinking quotas.

## The 5 dimensions

| Dimension | Module | Role |
|-----------|--------|------|
| **route** | `scheduler_router.py` | L3Router: intent → best agent (territory + reputation + load); RequestPool: tool requests scored `reputation×0.4 + priority×0.35 + wait×0.25` |
| **pool** | `scheduler_router.py` (RequestPool) | queued request scoring + dispatch |
| **time** | `scheduler_time.py` | fair-share CPU: quantum, preemption, weighted round-robin by (priority + wait_time) |
| **rate** | `scheduler_rate.py` | per-agent / per-ring rate limits (Ring1 60/min, Ring2.5 20/min, Ring3 5/min) |
| **scope** | `scheduler_scope.py` | step budgets (dynamic cap) + scout concurrency quotas |

Unified by `scheduler.py` (CentralScheduler, the 5D matrix assembly) over
the **ACB** (`acb.py`) — the process control block equivalent: slot-based,
versioned, observable, JSON-persistable agent state.

## Safety layers

| Module | Role |
|--------|------|
| `loop_detectors.py` | SHA256 fingerprint exact tool-loop detection + name-based coarse duplicate detection |
| `sequence_monitor.py` | per-Cell tool-call sequence n-gram anomaly detection — "every step legal, the sequence is an attack" |
| `think_registry.py` | thinking-config 3-layer override registry (Global/Cell/Agent): inherit / auto_balance / manual |

## Relation

- `l3-card-lifecycle.md`: ExecutionPlan step budgets come from
  ScopeScheduler; dispatch goes through the router.
- `l1-kernel.md`: the ACB pairs with the kernel ProcessTable (agents are
  processes); GateChain gates what the scheduler lets run.
