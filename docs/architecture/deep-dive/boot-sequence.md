# Boot Sequence & Lifecycle

> **Sources:** `src/l1/kernel/lifecycle.py`, `src/l3/boot/boot.py`, `src/l3/boot/lifecycle.py`
> **Entry:** `boot(agent_config, interactive) -> dict`

## Lifecycle State Machine

```
HALTED ──[install()]──→ INSTALLING ──[done]──→ BOOTING ──[success]──→ ACTIVE
HALTED ──[boot()]─────→ BOOTING (skip install if version matches)
BOOTING ──[fail]──────→ CRASHED
ACTIVE ──[shutdown()]─→ DRAINING ──[done]──→ HALTED
CRASHED ──[boot()]────→ BOOTING
```

Persistent record in `.praxis/lifecycle.json`:
```json
{
  "install_version": 1,
  "schema_version": "20260730.1",
  "last_boot": "2026-07-30T12:00:00Z",
  "last_boot_success": true,
  "last_shutdown": "2026-07-30T11:00:00Z",
  "last_shutdown_clean": true,
  "boot_count": 12,
  "lifecycle_state": "ACTIVE"
}
```

## Install Phase

Triggered on `should_install()`: first boot, schema version mismatch, or unclean shutdown.

```python
install()  # src/l3/boot/install.py
  ├── run_pending(schema_version → SCHEMA_VERSION)  # migrations
  ├── init_archive()                                 # archive DB (idempotent)
  ├── seed archive SYSTEM/lifecycle record           # first install only
  ├── seed card types (execution, review, issue, inspection)
  ├── mark install_version + schema_version
  └── transition(INSTALLING → BOOTING)
```

## Boot Phases

### Pre-steps (inside `boot()`, before DAG)

| Step | Action |
|------|--------|
| Lifecycle | Transition `HALTED → BOOTING` |
| Retry safety | If previous boot failed, `reset_all_singletons()` |
| Kernel OS wiring | `wire_kernel_os()` — register boot/shutdown/terminal/cell handlers |
| Bootstrap wizard | `needs_bootstrap()` → generate `praxis.yaml` if missing |
| Install check | `should_install()` → run `install()` |
| Shutdown handler | `register_shutdown_handler()` — atexit + SIGTERM/SIGINT |
| State restore | `l1.kernel.persist.restore()` |
| Auto-save | Background daemon thread (if `PERSIST_AUTO`) |
| Memory init | `init_from_memories()` → load agent config from prior snapshot |
| DAG init | Register 8 default steps → topo-sort → execute |

### Boot Steps (DAG, topologically sorted)

| # | Step | Depends On | Description |
|---|------|-----------|-------------|
| 1 | `load_constitution` | — | Load `.praxis-rules.md`, restore custom rules, detect assembly mode |
| 2 | `init_discovery` | 1 | Register params defaults, scan `config/discovery/*.yaml` |
| 3 | `load_config` | 2 | Load `praxis.yaml`, apply all section handlers |
| 4 | `load_tools` | 3 | Load `tools.yaml` into `TOOL_REGISTRY` |
| 5 | `init_system_bus` | 4 | SystemBus root + StatsCenter/RecordCenter/EventBus/CentralController |
| 6 | `init_services` | 5 | Kernel/VFS + Skills/Network + Memory/Archive/R4Agent/L3ADaemon |
| 7 | `init_record_center` | 6 | RecordCenter + StatsCenter bridge |
| 8 | `create_cell` | 7 | Cell with agents, scheduler, VFS mounts, CardRegistry dispatcher |

### init_services sub-functions

```
_init_kernel_and_vfs()
  ├── Constitution, event_bus, allocator, gatechain, swapper
  ├── VFS mounts: /project, /proc, /tmp, /sys, /dev, /skills
  ├── Device registration: llm, filesystem
  └── Config L2 → SettingsCenter

_init_skills_and_network()
  ├── SkillManager.load_builtin()
  ├── Network kernel start
  ├── HTN planner init
  └── Capability detector probe

_init_memory_and_archive()
  ├── MemoryManager.restore()
  ├── Archive: init_archive(), ring3_from_archive()
  ├── Daemons: start_r4_agent(), start_l3a_daemon()
  └── IssueTable, CacheDoc, CredentialVault, ToolMode, CentralSecurity, etc.
```

## Shutdown

```python
shutdown(wipe=False, cold_boot=False)  # src/l3/boot/lifecycle.py
  ├── transition(ACTIVE → DRAINING)
  ├── persist_all()     — MemoryManager Ring 2/3 to disk
  ├── archive_ring3()   — high-importance Ring 3 → Archive SQLite
  ├── snapshot_cells()  — Cell + agent state to JSON
  ├── stop_r4_agent()   — R4Agent daemon
  ├── stop_l3a_daemon() — L3A daemon
  ├── reset_all_singletons() — L4 → L3 → L1 order
  ├── wipe_disk_state() — optional
  ├── record_shutdown() — lifecycle.json
  ├── transition(DRAINING → HALTED)
  └── boot()            — optional cold boot
```

## Wiring Repair

`wire_kernel_os()` (in `boot.py`) fixes the previously broken `cmd_boot`:

```python
osys.register_boot_handler(boot)         # ← fixes python main.py boot
osys.register_shutdown_handler(shutdown)  # ← unified shutdown
osys.register_terminal_reset(reset_terminals)
osys.register_cell_reset(reset_cells)
```

## Extensibility

```python
from l3.boot.boot import register_boot_step
register_boot_step("my_step", my_fn, depends_on=["init_services"])
```

Steps are topologically sorted by dependency. Insertion after `lock_registry()` is rejected.
