# Cross-Cutting Concerns

Topics that span layers: governance, events, system-prompt injection,
session contract, port abstractions, and collaboration discipline.

## Governance (will cannot violate the constitution)

```
User will ──> L3A (central) ──card──> GateChain G1–G5 ──> tools
                  │                         ▲
                  └── constitution rules ───┘  (highest authority)
```

- **Constitution** (L1): rule engine over `.praxis-rules.md`; injected
  into every agent loop as a summary (gated `prompt.inject.constitution`).
- **GateChain** (L1): per-tool authorization — whitelist, identity
  (process table), territory/risk, escalation, composite judgment.
- **Approval flow** (L3): ApprovalGate + PendingQueue with event push
  (CARD_PENDING / APPROVAL_REQUIRED / APPROVAL_RESPONDED) — the same
  events drive the user profile decision-style collector.

## Event flow (one bus, many listeners)

```
emit_signal / emit_event → EventBus (async thread pool)
   ├─ history (bounded deque)
   ├─ typed listeners (on / on_event)
   ├─ wildcard listeners (on_any) → SSE bridge → /api/events
   └─ wildcard → WS bridge → subscribed clients (event-type filter)
```

```mermaid
sequenceDiagram
    participant S as Source (card registry / approval gate / hook)
    participant B as EventBus
    participant SSE as SSE bridge
    participant W as WS bridge
    participant F as Frontends

    S->>B: emit_signal(TYPE, data)
    B->>B: history + async dispatch (thread pool)
    B-->>SSE: on_any broadcast
    SSE-->>F: SSE /api/events (type filter)
    B-->>W: on_any broadcast
    W-->>F: WS event message (subscription filter)
    B-->>S: typed listeners (e.g. profile collector)
```

Cards: `EVENT_TASK_ASSIGN` / `TASK_DONE`; approval: `APPROVAL_*`;
monitor/stats events on the time bus (`stats.*`); hook events
(`agent.turn_complete` / `loop_error` / `session_end`) from
`EventEmitHook`.

**Signal subscribers (closed the orphan-signal gaps):** typed subscribers
now exist for every produced signal — Cell subscribes
`TASK_ASSIGN` / `REVIEW_REQUESTED` / `FILE_CHANGED` (+ `agent.turn_complete`
string event), ScoutPool subscribes `SCOUT_DONE`, `TASK_CANCEL` is emitted
by `subagent_task.cancel()` and `STATE_CHANGE` by the statecharts
transition `_apply`. `emit_signal` falls back to dynamic registration for
names outside the enum.

## Observability convergence (MonitorBus → StatsCenter)

Message, error and log streams converge on the MonitorBus and are ingested
into StatsCenter as `monitor.event.<type>` counters:

```
IPC / L3B / cell-mailbox → CommMonitor ("comm.message" / "l3b.message")
ErrorBus._ingest        → "error.bus" (fingerprint, severity-mapped)
LogService._log         → "log.entry" (level-mapped)
MonitorBus.emit         → StatsCenter ingest (monitor.event.<type> counter)
```

MonitorBus also exposes internal `subscribe()` / `unsubscribe()` (non-SSE)
listeners so components consume the stream without a frontend.

## System-prompt injection (user-configurable)

Each injectable block is gated by `prompt.inject.<domain>` (SettingsCenter
key, runtime toggle via `/api/v2/settings`, defaults true). On any settings
failure `l1.kernel.settings.inject_enabled()` falls back to enabled —
safety context is never silently stripped.

| Domain | Block | Gated in |
|--------|-------|----------|
| `profile` | `[User Profile Reference]` + card `_profile_summary` | `l3a/helpers.py` |
| `constitution` | constitution summary | `agent/agent_loop.py` |
| `skills` | evolved skills + lean failure cases | `agent/agent_loop.py` |
| `verification` | verification culture | `agent/agent_loop.py` |
| `memory` | task-aware memory context | `agent/_term_handlers.py` |

## Session contract (anti-blowup design)

- **Cursor paging**: `messages(cursor, limit)` — UI renders a window, pages
  backward; `API_PAGE_MAX_LIMIT` caps page size.
- **Kernel-side caps**: `SESSION_HISTORY_MAX_TOKENS=32000` compression,
  `MANAGED_OUTPUT_MAX_BYTES=50000` output spill, per-user profile caps.
- **Frontend-side** (future TUI): bounded event queue + frame throttling,
  display windowing — never unbounded accumulation.

## Port abstractions (language-agnostic kernel)

```python
register_port(name, adapter) / get_port(name)   # duck-typed
```

Adapters: `auth` (AuthService), `fs` (FsAdapter), `profile`
(UserProfileService), `rpc` (RpcServer); LLM/i18n/worker/channel/event-bus/
card-registry/monitor-bus/transport. The kernel never imports upper layers —
swapping the Python kernel for another language only changes adapters.

## Agent efficiency evaluation (cross-layer)

Throughput alone is not a valid efficiency measure for agents: a loop that
repeatedly emits steps rejected by the Verifier scores high on steps/s and
zero on value. Evaluation therefore combines **four metric families**, each
answering a different question:

| Family | Question | Signals / formulas |
|---|---|---|
| **Quality-weighted** | How much *useful* work per second? | effective throughput = raw throughput × Verifier pass rate; rework ratio = rejected steps / total; convergence efficiency = steps to card convergence (`convergence.py` RESOLVED share); quality-cost ratio = passed steps / LLM calls |
| **Latency distribution** | How bad is the *tail*? | p50/p95/p99 step latency (mean feeds throughput only); Little's Law cross-check `WIP = throughput × cycle time` — finds the concurrency where throughput stops rising (lock contention / serial dependency); wait share = agent idle / wall time (complements the thread-pool `active_ratio` in the load-adaptive design) |
| **Stall & oscillation** | Is the agent *spinning*? | stagnation rate = stagnation-trigger count / total steps; oscillation detection = zero-crossing / variance analysis of the EWMA `queue_ratio` series (feeds the load-adaptive hysteresis tuning); convergence-step histogram to surface long-tail cards |
| **Scaling curve** | Where is the serial bottleneck? | Amdahl fit `speedup = 1 / (1−P + P/N)` over agent counts 1→2→4→8 → serial fraction P (high P ⇒ scheduler/shared-lock bottleneck); Gustafson correction at fixed wall time; saturation knee N* = measured max useful concurrency for `praxis.yaml` |

Sources already in-tree: `src/l3/agent/verifier.py` (pass/fail),
`convergence.py` (resolution ratio), `stagnation.py` (loop detection),
`src/l3/scheduler/` (rate limits, step budgets), `tests/benchmarks/bench_card.py`
(wall time, steps/s, parallel efficiency, CPU/wall speedup),
`tests/benchmarks/bench_platform.py` (L1 primitives: mutex/event bus/channel/
worker pool/thread create; platform fingerprint incl. WSL; `--json` for
cross-platform diffing). The load-adaptive controller's `stats()` +
`load_adaptive_decision` events (see `docs/design/praxis-load-adaptive-pool-design.md`)
feed families 2–4; the scaling curve is the primary evidence for the Rust
kernel migration priorities.

## Testing & QA

- **3383 tests** under `tests/` organized by layer (`tests/l1/` … `tests/l5/`,
  `tests/infra/`, `tests/integration/`).
- **Singleton hygiene**: `tests/conftest.py` `_RESETS` resets ~33 known
  singletons before every test (autouse) — new services register their
  reset there; xdist workers get isolated skill dirs.
- **Runner batches**: `tests/runner.py` — Batch 1 (fast core), Batch 2
  (slow: r4_agent, archive, convention).
- **xdist discipline**: plain `pytest` runs `-n auto --dist loadfile` (pyproject
  default); Linux fork makes xdist profitable both locally (WSL) and in CI.
- **Hard gates**: `test_layer_imports.py` (layer boundary allowlist),
  `test_params_compliance.py` (no hardcoded truncation/hash/constants),
  `test_hardcoded_fixes_regression.py`.
- **CI**: GitHub Actions (dual-remote mirror), matrix 3.11/3.12, concurrency
  cancel-in-progress; GitCode AtomGit Action pending platform rollout.

## Skills lifecycle (agent growth)

```
builtin (config/skills, read-only) ── SkillManager (L1)
evolved (skills/evolved)       ←── R4Agent.evolve_skill (LLM SkillArchitect)
lean    (skills/lean)          ←── failure traces (dedup by exact name/key)
usage: bump_usage (atomic) / bind_skills per Cell / prompt.inject.skills
archive: pre-evolution + pruned versions → R4 (fonds="skills")
```

- Round-trip integrity: `SKILL.md` YAML frontmatter (name/description/
  tags/allowed_tools/variables) must round-trip on reload.
- Write gate: external callers (L2 shell `/skills`, L4 API) must pass an
  explicit identity; identity-less writes only with `internal=True`.
- Per-Cell injection: `Cell.bind_skills` whitelists; unbound cells fall
  back to the global pool.

## Collaboration discipline (agents)

- **7 work domains** (K/M/S/T/C/B/A), one branch per agent
  (`feature/<agent>-<area>`), merge order K → M/T/S → C/B → A.
- **One worktree per agent — FORBIDDEN to share a tree**:
  `bash scripts/check-worktree.sh` before any switch (rejects dirty trees
  exit 1, duplicate checkouts exit 2); `.githooks/post-checkout` warns on
  dirty carries. Two incidents on record (network-refactor drift,
  2026-08-05 shared-tree drift).
- **Per-agent gates**: layer-import + params-compliance + domain tests +
  full baseline + ruff green before push.
- **Dual remotes**: every push to main goes to GitCode (canonical) AND
  GitHub (CI carrier).
