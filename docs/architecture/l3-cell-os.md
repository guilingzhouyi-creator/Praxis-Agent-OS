# L3 — Cell Runtime (SoC components + boot + lifecycle)

A Cell is an agent's "system on a chip": 19 components in
`src/l3/cell/components/` map classic OS hardware onto the agent domain.
Boot brings the machine up; lifecycle takes it down cleanly.

## Cell components (the SoC)

| Component | OS analogue | Role |
|-----------|-------------|------|
| `cell_icache.py` | **I-Cache** | instruction cache (LFU eviction): tool definitions, card templates, constitution, territory maps — never flushed to memory |
| `cell_cache.py` | **D-Cache** | L2 shared cache: Hot Ring + Index Chain + KV, TTL; flush/promote to L3 MemoryManager |
| `cell_mmu.py` | **MMU + TLB** | translates territory paths → physical agent id with ring permissions; TLB caches recent translations |
| `cell_pmu.py` | **PMU** | performance counters (cards/tools/cache/bus/token/watchdog), sampled snapshots → MonitorBus |
| `cell_watchdog.py` | **Watchdog timer** | per-agent HEALTHY→UNRESPONSIVE→CRASHED escalation; auto-restart or NMI |
| `cell_interrupt.py` | **Interrupt controller** | 4-priority IRQ (NMI/HIGH/NORMAL/LOW), NMI unmaskable, wraps EventBus |
| `cell_rollback.py` | **Transaction rollback** | checkpoint + file snapshot + sandbox discard + terminal reset |
| `cell_permission.py` | **Capability table** | subagent delegation state machine (DISABLED/CELL_ENABLED/AGENT_GRANTED) + kill switch |
| `cell_state.py` | **Persistent state** | Cell (agents/card_history) save/restore JSON |
| `cell_token_merger.py` | **Accounting** | per-cell token accumulator → TOKEN_USAGE events |
| `cell_cross_review.py` | **Code review board** | blocking wait for peer CROSS_REVIEW_RESP after writes/deletes |
| `cell_convention.py` | **Deliberation policy** | convene() activates deliberation memory; peer agents share the Cell ring |
| `cell_decompose.py` | **Scheduler partition** | decomposes a card into sub-cards routed by territory |
| `cell_execute.py` | **Executor** | `Cell.execute_card()`: raw→card, decomposed slices, snapshot injection |
| `cell_lifecycle.py` | **Power management** | boot/shutdown/emergency/reset/restart mixin |
| `cell_messaging.py` | **IPC** | inter-agent send/read/liveness with mailboxes |
| `cell_monitor.py` | **Health monitor** | rolling event log for L3A queries/visualization |
| `cell_buffer.py` | **Ring buffer** | fixed circular buffer for rollback context / card history / snapshots |
| `cell_agent.py` | **Process manager** | agent register/query/status, mailbox init |
| `cell_types.py` | — | shared dataclasses/enums/protocols |

## Boot (bringing the machine up)

| Module | Role |
|--------|------|
| `boot.py` | main sequence: constitution → kernel services → Cell with 3 peer agents → register with scheduler/IPC/ACB/identity → heartbeat → L3 coordinator |
| `boot_registry.py` | extensible boot-step registry with dependency ordering + timeout |
| `install.py` | first-run/upgrade: schema migration, seed defaults, version marker |
| `lifecycle.py` | unified shutdown: stop intake → persist memory → Ring3 archive → stop daemons → reset singletons → optional disk wipe |
| `wiring.py` | **single source of truth** for port→adapter assembly (wire_defaults / wire_from_config) |

```
boot: install? → constitution → kernel services → Cell+3 agents
      → scheduler/IPC/ACB/identity registration → heartbeat → L3 coordinator
shutdown: stop intake → persist → archive → stop daemons → reset → (wipe?)
```

## Scheduler (5D) — see `l3-scheduler.md`

Time/rate/scope/router/pool scheduling over the ACB — the CPU scheduler of
the Cell SoC. `loop_detectors`, `sequence_monitor`, `think_registry`
provide the safety and quota layers around it.

## Relation

- Card execution (see `l3-card-lifecycle.md`) runs **on** this SoC: MMU
  checks the step's territory, PMU counts it, watchdog guards the agent,
  interrupt delivers events.
- Boot wiring is the shared-file register for port adapters (see
  `cross-cutting.md`).
