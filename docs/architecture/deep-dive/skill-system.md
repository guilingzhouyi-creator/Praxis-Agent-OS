# Skill System

> **Source:** `src/l1/kernel/skill.py` (SkillManager), `src/l3/memory/r4_agent.py` (R4Agent evolution),
> `src/l3/agent/agent_loop.py` (`_inject_extra_context`), `src/l3/cell/__init__.py` (Cell binding),
> `src/l1/kernel/paths.py` (layered persistence), `src/l3/tools/_skills.py` (list_skills / use_skill)

## Overview

Praxis skills are structured, reusable agent capabilities. They are managed by
the L1 `SkillManager` singleton (load/list/query/mutate) and evolved by the L3
`R4Agent` background daemon. Skills can be bound per-Cell, persisted in two
scopes (project/global), and linked into the R4 archive and R5 semantic graph.

```
SkillManager (L1)                       R4Agent (L3)
  load_dir / load_builtin  ←──────────  evolve_skill (LLM SkillArchitect)
  cell_skill_map (per-Cell white-list)  _process_failure_traces (lean cases)
  create/update/delete (write gate)     _prune_stale_skills (TTL)
  bump_usage (atomic counter)           _clean_orphan_traces (24h)
  _emit_mutated → event bus             → R4 archive (fonds="skills")
                                        → R5 MemoryGraph edges
```

## Skill Record

A skill is a dict with a uniform schema (all producers agree on it):

| Field | Type | Notes |
|-------|------|-------|
| `name` | str | unique key, kebab-case |
| `description` | str | one line, ≤200 chars |
| `prompt` | str | system prompt injected into agents |
| `rules` | list[str] | `DO:` / `DON'T:` constraints |
| `procedures` | list[dict] | step/action/description |
| `tags` | list[str] | `evolved`, `lean_case`, agent id, tool |
| `allowed_tools` | list[str] \| None | None = all tools |
| `variables` | list[str] \| None | `$VAR` placeholders for `expand()` |
| `source` | str | file path or `"evolved"` |
| `loaded_at` / `last_used` | float | lifecycle timestamps |
| `useful_count` | int | atomic usage counter (see bump_usage) |

## Evolution Strategies

### 1. LLM Skill Architect (`evolve_skill`)

```
user intent → LLM (r4_agent.skill_architect prompt) → JSON
            → sm.create() + persist SKILL.md + bind to Cell (optional)
            → R4 archive pre-evolution version + R5 refines/type_chain edges
```

- Prompt requires `name`, `description`, `prompt`; allows `rules`,
  `procedures`, `tags`, `allowed_tools`, `variables`.
- LLM output is normalized (`or []` / `or ""`) so `null` fields never crash.
- Versioning is atomic: backup first, then overwrite-create — the old skill is
  never deleted before the replacement exists.
- Write scope is `project` (default, `<package-root>/skills/evolved`) or
  `global` (`data_dir/skills/evolved`), configured via `skill.evolve_scope`.

### 2. Lean Cases (`_process_failure_traces`)

```
tool failure → track_tool_failure() → JSON trace → lean case skill
             → R4 archive (series="lean_trace") + R5 depends_on edge
```

- Dedup: exact name or `dedup_key + "_"` prefix match — never raw substring
  (would collide `rm` vs `rmdir`).
- Same-scan duplicates are skipped (new names added to the seen set).
- Naming: `lean_{agent}_{tool}_{error_stem}`.
- Injection: `AgentLoop._inject_extra_context` shows them as
  "Known Failure Patterns".

### 3. TTL Pruning (`_prune_stale_skills`)

- Evolved skills unused for `SKILL_TTL_DAYS` (default 7) are pruned.
- Before deletion the skill is archived (`fonds="skills", series="pruned"`)
  and its persisted SKILL.md directory is removed (project + global scope) so
  it does not resurrect on the next boot.
- Lean cases and built-in skills are exempt.
- Orphan trace files older than 24h are cleaned by `_clean_orphan_traces`.

## Per-Cell Binding (回灌到 Cell)

`SkillManager` keeps `cell_skill_map: cell_id → set[skill_names]`.

- `Cell.bind_skills(names)` white-lists skills for a Cell (delegates to L1).
- `AgentLoop._inject_extra_context` filters `get_evolved_skills` /
  `get_lean_cases` by `self._cell_id` — bound Cells only see their skills.
- Unbound Cells fall back to the global pool (backward compatible).
- Config: `cell.skills: {cell-id: [skill-a, ...]}` in `config/praxis.yaml`;
  boot reads it and binds automatically.
- Deleting a skill drops it from every Cell binding.

## Layered Persistence & Project Generalization (项目泛化)

| Scope | Write target | Discovery |
|-------|--------------|-----------|
| `project` (default) | `<package-root>/skills/evolved` | `skill_dirs` includes `skills/evolved` (CLI_PROJECT) |
| `global` | `data_dir/skills/evolved` | loaded via `load_builtin` data-dir path |

- The write target and the discovery list MUST stay in sync — if they drift,
  evolved skills silently disappear after reboot.
- `git clone` a project → its `skills/evolved` travels with the repo → boot
  auto-discovers them. `PRAXIS_SKILL_DIR` env var overrides all.
- `config/praxis.yaml skill.project_dirs` appends extra discovery dirs.

## R4 Archive Linkage

| Event | fonds / series |
|-------|----------------|
| Re-evolution (old version) | `skills` / `evolved` |
| TTL prune before delete | `skills` / `pruned` |
| Failure trace | `skills` / `lean_trace` |

All archive calls are best-effort (`try/except`); failures never block the
main skill flow.

## R5 MemoryGraph Linkage

- Evolution with versioning adds a `refines` edge (old → new) and a
  `type_chain` edge via `remember_hook` with `entry_type="skill"`.
- Lean cases add a `depends_on` edge (failing tool → case).
- `get_evolved_skills(graph_diffusion=True)` recalls along graph edges and
  falls back to linear order when the graph is disabled or empty.
- The R5 graph switch defaults OFF (`memory.graph.enabled`); every hook is
  non-blocking.

## Write Gate & Security

`authorize_write(agent_id, role, internal=False)`:

- External callers (L2 shell `/skills`, L4 API) MUST pass an explicit
  identity — identity-less calls are rejected with
  "identity required: provide agent_id or role".
- Identity-less writes are allowed ONLY with `internal=True` from system
  processes (boot loading, R4Agent evolution/pruning).
- Roles pass if in `skill.write_roles` or `ring >= skill.write_min_ring`
  (default `("l3","reviewer","deployer")`, ring 3).
- The gate protects Cell bindings and TTL deletes too — never weaken it.

## Runtime Injection

`AgentLoop._inject_extra_context` (bounded by `LOOP_CONTEXT_BUDGET_SKILL`):

1. `get_lean_cases(cell_id, limit=LOOP_LEAN_CASES_LIMIT)` →
   "Known Failure Patterns" block.
2. `get_evolved_skills(cell_id, limit=LOOP_EVOLVED_SKILLS_LIMIT)` →
   `### name` blocks, truncated by `LOOP_EVOLVED_SKILL_TRUNC`.
3. Cross-cell rules appended when the coordinator is active.

`SkillCatalogHook` (L3) additionally lists the 5 most recent skills at session
start. Both share the same budget philosophy: bounded, truncated, never
overflowing the context window.

## Usage & Observability

- L2 Shell: `/skills list|get|create|update|delete|reload|evolve|permissions`
  (mutations require `--role`/`--agent` identity).
- L4 API: `/api/skills` GET/POST/PUT/DELETE + `/reload` + `/permissions`.
- Audit: mutations emit `skill_mutated` via the event bus
  (`get_bus().emit_event` — NOT `emit_signal`, whose `SignalType` enum has no
  member for it).
- PMU counters: `skills.lean.generated`, `skills.evolved.created`,
  `skills.evolved.injected`.

## Tests

- `tests/l1/test_kernel_extended.py` — gate, sort, query, round-trip.
- `tests/l3/memory/test_r4_skill_evolution.py` — dedup, TTL, orphan cleanup.
- `tests/l3/memory/test_skill_integration.py` — VFS, hook, config, Cell binding,
  graph fallback, R4 hooks.
- `tests/l3/memory/test_r4_agent_evolve*.py` — evolve_skill full flow.
- `tests/l2/test_l2_shell_integration.py` — `/skills` subcommands.
