# Collaboration Plan — Parallel Peer Development

> Status: proposed | Applies to all collaborators (humans and agent tools)
> Companion to: `docs/workflow/branching.md` (branch policy), `AGENTS.md` (conventions)

## 1. Goal

Enable multiple peer agents to build Praxis in parallel without merge collisions.
Each agent owns one work domain, opens one `feature/*` branch, and merges only
when its domain tests + the full baseline are green.

## 2. Work domain partition (git-boundary based, minimal overlap)

| Domain | Agent ID | Source scope | Test scope | Notes |
|--------|----------|--------------|------------|-------|
| K — Kernel core | `k-agent` | `src/l1/kernel/` (incl. `params/`) | `tests/l1/` + `tests/infra/` | Highest risk: gatechain, VFS, params constants. Single-owner only. |
| M — Memory system | `m-agent` | `src/l3/memory/` | `tests/l3/memory/` | Hot zone: R5 memory graph, Mer side-channel, R4 archive. Owns `memory_graph.db` migration logic. |
| S — Sessions & subagents | `s-agent` | `src/l3/cell/peers/l3a/`, `src/l3/agent/subagent*`, `src/l3/subagent/` | `tests/l3/l3a/` + `tests/l3/subagent/` | Hot zone: L3A session system, subagent pool. |
| T — Tool pipeline | `t-agent` | `src/l3/tools/`, `src/l3/tool_system/`, `config/tools.yaml` | `tests/l3/tools/` + `tests/l3/tool_system/` | Hot zone: mute semantics, ToolSpec, 9-step pipeline. |
| C — Card / scheduler / cell orchestration | `c-agent` | `src/l3/card/`, `src/l3/scheduler/`, `src/l3/cell/components/`, `src/l3/cell/peers/` (except `l3a/`) | `tests/l3/card/` + `tests/l3/scheduler/` + `tests/l3/cell/` | Excludes l3a/ (owned by S). |
| B — Bus / discussion / services | `b-agent` | `src/l3/bus/`, `src/l3/discussion/`, `src/l3/services/`, `src/l3/error_bus/`, `src/l3/resource_buffer/`, `src/l3/config/` | `tests/l3/bus/` + `tests/l3/discussion/` + `tests/l3/services/` + `tests/l3/config/` + `tests/l3/error_bus/` | |
| A — Bridge / Shell / API | `a-agent` | `src/l4/`, `src/l5/`, `src/l2/`, `config/` (except `tools.yaml`) | `tests/l4/` + `tests/l5/` + `tests/l2/` + `tests/integration/` | API gateway, sandbox, LLM providers, i18n. |

Boundary rule: a file belongs to exactly one domain. Agents never touch files
outside their domain without announcing in the shared-file register (section 4).

## 3. Branch strategy

```
main                      stable, shippable, tests green
feature/<agent>-<area>    one branch per agent per feature, e.g. feature/m-agent-memory-graph-v2
```

- Each domain agent works on its own branch; never commit onto another agent's branch.
- Merge order recommendation (respect dependency direction):
  1. `k-agent` (params/kernel are compile-time defaults for everyone)
  2. `m-agent`, `t-agent`, `s-agent` (leaf systems)
  3. `c-agent`, `b-agent`
  4. `a-agent` (shell/API consumes all lower layers)
- Double-green rule: branch tests pass AND main tests pass (`--no-ff` merge).
- If a merge conflicts: the branch merged later rebases onto main (`git rebase main`),
  resolves conflicts, re-runs its domain tests, then merges.

## 4. Shared files register (no parallel modification without announcement)

These files cross domain boundaries. Only one agent may modify them at a time;
announce intent (in commit message of the announcing commit, or this file) first:

| Shared file | Why | Preferred owner |
|-------------|-----|-----------------|
| `src/l3/cell/peers/l3.py` | CentralController hub: L3A + L3B + CardRegistry | c-agent, coordination with s-agent |
| `src/l1/kernel/params/*.py` | 694 constants; strict compliance test | k-agent (others: add via review, not parallel) |
| `src/l3/boot/` (boot.py, wiring.py) | all domains depend on wiring | b-agent |
| `tests/conftest.py` | singleton reset registry `_RESETS` | whoever adds a new singleton; must not conflict |
| `tests/infra/test_layer_imports.py` | cross-layer allowlist | whoever adds a new cross-layer import |
| `src/*/__init__.py` | export symbols | domain owner; conflicts resolved by rebase |
| `config/praxis.yaml` | deployment config | a-agent (with announce) |
| `docs/workflow/branching.md`, `docs/workflow/collaboration.md` | policy docs | any agent, merge on main quickly |

## 5. Per-agent verification matrix (before any push)

Every agent must run, on its branch, before push:

```bash
python -m pytest tests/infra/test_layer_imports.py -x -q    # layer constraint
python -m pytest tests/infra/test_params_compliance.py -x -q  # params constants (strict)
python -m pytest tests/<domain>/ -x -q                       # domain tests
python -m pytest tests/ -q                                   # full baseline (2900 tests)
ruff check src/ tests/                                       # lint
ruff format --check src/                                     # format (double quotes, 120)
```

Small-fix path (single-file bug/doc/test) may commit directly to main per
branching.md section 3, but still must pass the domain + layer tests.

## 6. Handoff protocol

- Every commit: English message, `Co-Authored-By` trailer (see AGENTS.md).
- Feature-complete branch: tag the last commit with the domain + summary in the
  merge commit body, listing touched shared files.
- Cross-domain API changes (new params constant, new registry export, new
  singleton): must be committed to main FIRST (small commit) before the
  consuming domain's branch is merged — avoids rebase cascades.
- Interrupted work: never leave in-flight changes in the working tree
  (branching.md section 5). Stash with a note or commit WIP on the feature branch.

## 7. Ownership of runtime artifacts

| Artifact | Owner |
|----------|-------|
| `memory_graph.db`, `memories/` | m-agent (schema/migration), others read-only |
| `.praxis_sandbox_state.json`, `config/.praxis-rules.md` | a-agent, constitution changes announced |
| `locales/` | a-agent (i18n) |
| `tests/runner.py`, `tests/conftest.py` | shared; announce changes |
