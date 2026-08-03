# Praxis Agent OS — Reference

> **Audience:** Developers, operators. Reference material, not narrative.
> **Corresponds to:** actual code tree under `src/`.
>
> **Note:** The file layout below is historical. For current authoritative
> documentation of the evolved subsystems (L3A session system, unified
> lifecycle, MCP server mode), see the deep-dive docs:
>   - `docs/architecture/deep-dive/l3a-assembly.md — L3A session/subagent/task-table/TODO/MCP
>   - `docs/architecture/deep-dive/card-lifecycle.md — CardRegistry + subscription/approval
>   - `docs/architecture/deep-dive/boot-sequence.md — lifecycle state machine + install
>   - `docs/architecture/deep-dive/layer-restructure-plan.md — L3→L2 sinking plan

## New Subsystems (post-restructure)

```
src/l1/kernel/
├── lifecycle.py            # LifecycleState machine + persistent registry
├── migration.py            # SCHEMA_VERSION + migration executor

src/l3/boot/
├── install.py              # first-run/upgrade: migrations + seed data
├── lifecycle.py            # unified shutdown() (persist→archive→stop→reset)

src/l3/cell/peers/l3a/      # L3A session system (12 modules)
├── __init__.py             # L3ADaemon + singleton
├── session.py              # Session/SessionHistory/SessionManager
├── task_table.py           # SessionTaskTable (card task monitor buffer)
├── subagent.py             # L3ASubAgentPool + spawn/collect/peek
├── context.py              # ContextEpoch/ContextSource/ContextRegistry
├── inbox.py                # PromptInbox (durable admission/promotion)
├── model.py                # L3AModelConfig (inheritance chain)
├── archive.py              # R4 archive store/restore
├── pipeline.py             # ManagedToolOutput spill
├── helpers.py              # cardwrite handler, prompt builder
├── api.py                  # /l3a L2 Shell routing
├── types.py / params.py

src/l4/api_handlers/
└── api_handlers_mcp.py     # MCP server mode (tools/list, tools/call, ping)

```

## File Layout (complete)