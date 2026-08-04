# Praxis — Agent Operating System

**This is not a game project.** Praxis is a five-layer Agent Operating System that maps traditional OS concepts (kernel, process, memory, file system, security) onto LLM-based AI agents.

| OS Concept | Praxis Implementation |
|---|---|
| CPU instruction set | `ToolSpec` (tool name, params, handler) |
| Process | `AgentTerminal` (PCB, thread pool, stdin/stdout queues) |
| System calls | `ToolPipeline` (9-step execution pipeline) |
| Virtual file system | `VFS` with ring-level access control |
| Memory management | 4-tier ring memory (R1 working → R4 archive) |
| MMU + TLB | `CellMmu` + `CellTlb` (territory→agent translation) |
| Interrupt controller | 4-priority `InterruptController` (NMI/HIGH/NORMAL/LOW) |
| Performance counters | `CellPmu` (49 counters across 12 groups) |
| Security gates | `GateChain` G1-G5 (constitution → clearance → audit) |
| Boot sequence | 7-step topological bootstrap + health check |

## Quick start

```bash
pip install -e ".[test]"
python src/main.py boot           # Boot the kernel
python src/main.py status         # System status
python -m l2.l2_shell             # Interactive agent shell
curl http://localhost:8080/api/health  # API health check
```

## Architecture

```
L5 — User Layer          (l5/cli.py, agent_runtime.py)
L4 — Bridge Layer        (API gateway, LLM engines, sandbox)
L3 — Cell Layer          (agents, memory, scheduler, cards)
L2 — Shell Layer         (40-command shell, i18n)
L1 — Kernel Layer        (sync, process, VFS, gatechain)
```

**Docs:** [Architecture Overview](docs/architecture/overview.md) | [Reference](docs/architecture/reference.md) | [Agent instructions](AGENTS.md)

## What is a "Card"?

Not a playing card. `Card` is Praxis's **unit of work** — analogous to a process control block or a job descriptor:

```
Card.submit()   → queue the work
Card.approve()  → authorize execution
Card.execute()  → run phases/steps against agents
Card.complete() → persist results
```

## What is a "Cell"?

Not a biological cell or game grid. `Cell` is Praxis's **scheduling unit** — analogous to a CPU core:

```
Cell holds N AgentTerminals (thread pools)
Cell routes Cards to the right agent by territory
Cell monitors liveness via Watchdog (hardware-style)
Cell tracks performance via PMU (hardware counters)
```

## Project structure

```
src/
├── l1/kernel/          # 44 files — OS primitives, params (817 constants, 8 sub-modules)
├── l2/                 # 16 files — Shell layer (40 commands)
├── l3/                 # 205 files — Cell layer (~19K lines)
│   ├── card/           # Unit-of-work lifecycle (NOT playing cards)
│   ├── agent/          # AgentLoop execution engine
│   ├── cell/           # Agent orchestration unit
│   └── memory/         # 4-ring hierarchical memory
├── l4/                 # 49 files — Bridge layer (API gateway, LLM, sandbox)
├── l5/                 # 2 files — User CLI
├── main.py             # Entry point
├── tool_ring.py        # Per-agent tool ring
└── tool_approval.py    # Ring 3 approval/witness
```

## Test

```bash
python -m pytest tests/test_kernel.py -x -q
python tests/runner.py                    # Batch 1 (fast) + 2 (slow)
python -m pytest tests/test_layer_imports.py -x -q
```
