# L1 — Kernel Layer

The bare-metal kernel: what every upper layer builds on. 46 files /
12,739 lines; 961 constants across 9 `params/` modules.

## Responsibility boundary

- Owns process, memory, synchronization, events, security gates, and the
  port abstraction — **nothing above L1 may be imported by L1**.
- Upper layers reach kernel facilities only through: syscall-style module
  imports, the event bus, port adapters, and `params/*` constants.

## Core modules

| Module | Role |
|--------|------|
| `process.py` | ProcessTable + PCB (agents are processes: ring, state, identity, audit) |
| `sync.py` | Mutex / Semaphore / Barrier / RWLock (RLock-reentrant) |
| `event.py` | EventBus: typed `SignalType` (21 members incl. card/approval flow), async dispatch via thread pool, string-event registry |
| `constitution.py` | Constitutional rules engine (highest authority; `.praxis-rules.md`) |
| `gatechain.py` | G1–G5 tool authorization chain (whitelist/identity/territory/escalation/composite) + stagnation callback |
| `ports.py` | 12 `*Port(ABC)` abstractions + `register_port`/`get_port` registry |
| `allocator.py` | Token allocation + GC |
| `vfs.py` / `registry.py` / `registry_base` | Virtual FS, system registry |
| `os.py` | Lifecycle: boot/shutdown/restart/watchdog |
| `ipc.py` / `net.py` / `net_transport.py` | IPC channel, cross-cell mesh, TLS transport |
| `process.py` audit, `reputation.py` trust, `swapper.py` ring swapping, `interrupt.py` IRQ table |
| `skill.py` | SkillManager (load/create/evolve/usage, write-gated) |
| `prompts.py` | Prompt registry (L3A system/parse templates, verification culture) |
| `params/*` | 961 compile-time constants (kernel/allocator/sync/gatechain/agent/tool/api/system/…) |

## Core mechanisms

### Event bus (async dispatch)

```
emit_signal(type, sender, target, data) → Signal → history + thread-pool dispatch
on(type, cb) / on_any(cb) / on_event(str, cb)   ← SSE/WS bridges subscribe on_any
String events auto-register (emit_event) — extensible without enum changes.
emit_signal resolves static enum members first, then falls back to dynamic
registration (register_signal_type) — unknown names never raise KeyError.
```

### GateChain (G1–G5)

```
G1 whitelist → G2 identity (process table) → G3 territory+risk → G4 escalation → G5 composite
BLOCK stops tool execution; WARN passes with audit. Ledger records every check.
```

### Port abstraction

```python
class AuthPort(ABC): issue_token / verify_token / revoke_token / refresh_token
class WebSocketPort(ABC): upgrade / recv(conn) / send(conn) / close(conn) / broadcast
class RpcServerPort(ABC): register_handler / call / notify
class FilesystemPort(ABC): read / write / list_tree / watch
+ TransportPort, ChannelPort, EventBusPort, WorkerPort, I18nPort,
  CardRegistryPort, MonitorBusPort, LLMPort
```

Adapters self-register (`register_port("auth", svc)`) at service init or
boot wiring; consumers resolve via `get_port(name)` — **duck-typed, so a
language-agnostic kernel can swap adapters without import changes**.

## Key constants (params)

- `PROCESS_DEFAULT_RING`, `PROCESS_AUDIT_MAX`, `PROCESS_TABLE_MAX`
- `EVENT_BUS_WORKERS`, `EVENT_BUS_MAX_QUEUED`
- `GATECHAIN_*` risk/repeat thresholds
- `AUTH_SIGN_KEY_BYTES`, `AUTH_TOKEN_TTL_SECONDS`, `API_PAGE_MAX_LIMIT`,
  `API_WS_PORT`, `RPC_SERVER_PORT`
- `LOG_TRUNC_*`, `HASH_TRUNC_*` (truncation discipline — never inline)

## Config surface

- `config/praxis.yaml`: kernel/gatechain/constitution sections
- SettingsCenter keys: `prompt.inject.*`, `user_profile.enabled`,
  `memory.graph.enabled`, `memory.mer.enabled`
