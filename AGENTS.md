# Praxis — Agent OS (v0.4.2 "Aether")

Python 3.11+ Agent OS for orchestrating LLM-based agents. Five-layer architecture from bare-metal kernel to user CLI.

## Quick start

```bash
pip install -e ".[test]"          # install + dev deps
python src/main.py boot           # boot kernel + cell
python src/main.py health         # kernel self-test
python src/main.py status         # full system status
python src/main.py ps             # list processes
python src/main.py card "<intent>"  # dispatch a card
python -m l2.l2_shell             # interactive L2 Shell
```

## Test commands

```bash
python -m pytest tests/ -x -q                                               # all tests (auto-discovers subdirs)
python tests/runner.py                                                      # batch 1 (fast) + batch 2 (slow)
python -m pytest tests/l1/test_kernel.py -x -q                             # single file (L1 kernel)
python -m pytest tests/l4/test_sandbox.py -x -q                            # single file (L4 sandbox)
python tests/runner.py --batch 1|2                                          # runner takes --batch ONLY (no test-name arg)
python -m pytest tests/ -k "kernel" -x -q                                   # keyword filter (works across subdirs)
python -m pytest tests/l2/test_l2_shell.py -x -q                           # L2 shell test
python -m pytest tests/infra/test_layer_imports.py -x -q                    # layer import constraint
python -m pytest tests/infra/test_params_compliance.py -x -q                # params constant compliance (strict)
python -m pytest tests/infra/test_params_compliance.py -k "not strict" -x -q # params constant compliance (soft)
python -m pytest tests/infra/test_hardcoded_fixes_regression.py -x -q       # regression: hardcoded fixes
```

## Architecture

```
src/l5/ — User layer: cli.py (~360 lines), agent_runtime.py
src/l4/ — Bridge: API gateway, LLM engine+providers, sandbox, MCP, search, LSP, vault
src/l3/ — Cell layer (~59K lines): agents, memory, cards, scheduler, tool pipeline, discussion
src/l3/cell/peers/l3a/ — L3A orchestration daemon: session system, subagent pool, context epoch
src/l3/cell/peers/l3.py — CentralController: L3A sessions + L3B routing + CardRegistry lifecycle
src/l2/ — Shell: 49 YAML commands + code-registered `_cmd_*` handlers, i18n, agent selector
src/l1/kernel/ — Kernel primitives: sync, event, constitution, allocator, gatechain, VFS, IPC
src/l1/kernel/params/ — ~1,000 constants across 8 sub-modules (kernel/allocator/sync/gatechain/agent/tool/api/system)
src/l1/kernel/ports.py — 12 `*Port(ABC)` abstractions; adapters wired at boot via `register_port()`/`get_port()` in `src/l3/boot/wiring.py`
```

### Import rules (enforced by `tests/infra/test_layer_imports.py`)
- L5 → L4/L3/L2/L1; L4 → L3/L2/L1; L3 → L2/L1; L2 → L1 only; L1 cannot import upper layers
- 93 pre-existing cross-layer imports are allowlisted in that test

## Key conventions

- **All magic numbers go in `src/l1/kernel/params/`** — never hardcode in implementation files
- **New kernel modules** must be exported in `kernel/__init__.py` `__all__`
- **New config items** register defaults in `kernel/settings.py` `DEFAULTS`
- **Use `threading.RLock`** (reentrant) for thread locks
- **Never import `services/` inside `kernel/`** — one-way dependency
- **Register tools** via `ToolSpec` with ring/danger/parameters in `config/tools.yaml`
- **No bare `except:`** — use `except Exception:`
- **Double quotes** for strings (ruff `quote-style = "double"`), line-length 120
- **Generalized constants rule (covers the specific entries below)**: any
  value with a fixed meaning — numbers, truncation/hash lengths, timeouts,
  file-path strings, memory weights — goes in `params/` and is referenced
  by name. The per-domain constants that follow are the most-used instances:
  `LOG_TRUNC_*`/`HASH_TRUNC_*` (truncation), `MEMORY_IMPORTANCE_*`/
  `MEMORY_PRESSURE_*` (weights), `TOOL_PACKAGE_MANAGER_TIMEOUT`/
  `TOOL_PIP_INSTALL_TIMEOUT` (timeouts), plus `paths.py` for path strings.

## Skill system (L1 kernel + L3 R4Agent)

Skills live in `src/l1/kernel/skill.py` (SkillManager singleton) and are evolved
by the L3 R4Agent (`src/l3/memory/r4_agent.py`). Architecture:

```
SkillManager (L1)                       R4Agent (L3)
  load_dir / load_builtin  ←──────────  evolve_skill (LLM SkillArchitect)
  cell_skill_map (per-Cell white-list)  _process_failure_traces (lean cases)
  create/update/delete (write gate)     _prune_stale_skills (TTL)
  bump_usage (atomic counter)           _clean_orphan_traces (24h)
  _emit_mutated → event bus             → R4 archive (fonds="skills")
                                        → R5 MemoryGraph edges
```

Key conventions:

- **Round-trip integrity**: `evolve_skill` persists skills as `SKILL.md` with
  full YAML frontmatter (`name`, `description`, `tags`, `allowed_tools`,
  `variables`). `_load_markdown` restores ALL of these on reload — never add a
  persisted field to one side without the other, or skills degrade to a
  tag-less form after a reboot.
- **Write gate**: `authorize_write(agent_id, role, internal=False)` — external
  callers (L2 shell `/skills`, L4 API) MUST pass an explicit identity;
  identity-less writes are only allowed with `internal=True` from system
  processes (boot loading, R4Agent evolution/pruning). Never weaken this gate:
  it also protects Cell bindings and TTL prune deletes.
- **Per-Cell injection**: `Cell.bind_skills(names)` white-lists skills for a
  Cell; `AgentLoop._inject_extra_context` filters by `cell_id`. Unbound Cells
  fall back to the global pool. Config: `cell.skills` in `config/praxis.yaml`.
- **Layered persistence**: `skill.evolve_scope` (praxis.yaml) — `project`
  (default, writes to `<package-root>/skills/evolved`, travels with the repo)
  or `global` (writes to `data_dir/skills/evolved`). The discovery dirs in
  `paths.py` CLI_PROJECT list MUST stay in sync with the write target, or
  evolved skills silently disappear after reboot.
- **R4/R5 linkage**: evolution archives the pre-evolution version
  (`fonds="skills", series="evolved"`), TTL prune archives before delete
  (`series="pruned"`), failure traces archive as `series="lean_trace"`.
  When the R5 graph is enabled, evolution adds `refines`/`type_chain` edges
  and lean cases add `depends_on` edges; all graph calls are non-blocking.
- **Dedup**: lean-case dedup matches exact name or `dedup_key + "_"` prefix —
  never raw substring (would collide `rm` vs `rmdir`).
- **Atomic counters**: use `SkillManager.bump_usage(name)` for useful_count /
  last_used increments (single-lock RMW) — never get-then-update in callers.
- **Audit**: skill mutations emit `skill_mutated` via the event bus
  (`get_bus().emit_event`), NOT `emit_signal` (the SignalType enum has no
  member for it — `emit_event` auto-registers the string type).
- **R5 graph switch** defaults OFF (`memory.graph.enabled`); all graph hooks
  must degrade gracefully (try/except + linear fallback).

## L3 + L4 conventions (enforced during code review)

- **Use `l1.kernel.platform` abstractions** for all OS-specific operations: `grep_cmd()`, `run_shell()`, and the `IS_*` OS-family flags (`IS_POSIX`, `IS_LINUX`, `IS_MAC`). Never self-implement platform-specific subprocess calls (e.g., `rg` → `grep` fallback with `shell=True`).
- **ConfigDiscovery** — structural configuration goes in `config/discovery/*.yaml`, auto-discovered at boot. See `docs/configuration/overview.md`.
- **Three-layer config**: `params/*.py` (compile-time defaults) ← `config/discovery/*.yaml` (structural overrides) ← `config/praxis.yaml` (deployment config).
- **Constants**: per-domain magic values (`LOG_TRUNC_*`, `HASH_TRUNC_*`,
  memory weights, timeouts, path strings) follow the generalized rule in
  `## Key conventions` — reference them by name, never inline.

## Comment conventions

- **English is the baseline language for ALL comments, docstrings, and module/class/function docs** — CJK is only allowed inside intentional data (i18n translation dicts, injection-detection keywords). A comment audit runs periodically; 0 CJK residue is the target.
- **Module docstring required** for every module (one-liner explaining purpose is enough); `commands/*.py` in L2 included.
- **Class docstring required** for every public class (dataclasses included — one line describing the role).
- **Public function docstring required** (what it does + returns); simple getters/setters and private helpers (`_*`) may skip.
- Docstring style: triple-double-quoted, first line = short imperative/descriptive sentence; sections (Args/Returns/Examples) only when non-obvious.

## Commit conventions (enforced by `.githooks/commit-msg`)

- **Commit messages MUST be written in English** (CJK characters are rejected).
- **Every commit MUST carry a `Co-Authored-By` trailer** naming the authoring agent/model for attribution:
  `Co-Authored-By: OpenCode (deepseek-v4-flash) <noreply@opencode.ai>`
- Merge/revert commits are exempt from the two rules above (git-generated
  messages), BUT a merge that brings in a dependabot branch is gated on its
  diff scope — see `## Dependency management`.
- **Hook mechanics (read before trusting the gate)**: `commit-msg` runs
  BEFORE the commit object exists, so `HEAD` still points at the previous
  commit. Any merge gate must therefore read the incoming branch from
  `.git/MERGE_HEAD` during `git merge` (git removes it after commit),
  falling back to `HEAD^2` only for manual post-merge commits. Detection
  triggers on the merged-tip **author** (`dependabot[bot]`) OR the message,
  so a hand-typed message cannot bypass it. It is NOT triggered by ordinary
  feature-branch merges.
- **Explicit bypass paths (forbidden unless justified)**: `git merge
  --no-verify` / `git commit --no-verify` skip ALL hooks, and
  `PRAXIS_SKIP_AUTHOR_CHECK=1` skips the message checks only. These are
  deliberate escape hatches for broken-hook recovery, not routine
  workflows. A `--no-verify` dependabot merge that drags in code WILL slip
  through the local gate — server-side backstops are GitCode's GPG hook and
  the deps.yml PR gate. Do not do it; if you did, the merge must be
  reviewed by a second agent before push.
- **GPG signing is mandatory for main**: GitCode's pre-receive hook rejects
  unsigned commits. `commit.gpgsign` is `true` globally; if a local
  `commit.gpgsign=false` override exists (it has happened), remove it —
  otherwise the push will be rejected and the commit must be re-signed
  (`git reset --soft HEAD~1 && git commit` with signing restored).

## Remote strategy & CI

- **Dual remotes**: `origin` = GitCode (`gitcode.com/Aplese/PraxisAgentOS`, canonical source of truth); `github` = GitHub mirror (`guilingzhouyi-creator/Praxis-Agent-OS`, CI carrier).
- **Every push to main MUST go to BOTH remotes**: `git push origin main; git push github main`. Pushing only to GitCode silently skips CI.
- **CI runs on GitHub Actions** via `.github/workflows/test.yml` (native GitHub format, matrix 3.11/3.12/3.13, full L1–L5 coverage incl. L3 root + L5 + memory R4 + API endpoint manifest; infra/L1/L5 steps pin `-n 0`, directory steps use pyproject `-n auto` — Linux fork makes xdist profitable there). Siblings: `ci.yml` (changed-file ruff gate), `codeql.yml`, `docker.yml`, `benchmark.yml`, `nightly.yml` (full-tree ruff).
- GitCode's AtomGit Action (`.gitcode/workflows/test.yml`) is still in gray release (no Pipeline tab even on public repos) — keep the file, it activates once the platform rolls it out.

## Dependency management

- **Dependabot opens dependency PRs automatically** (`.github/dependabot.yml`):
  weekly for pip, monthly for GitHub Actions. They are **NOT auto-merged** —
  every dependabot branch must go through the double-green merge flow.
- **A dependency bump MUST be validated before merging**: after touching
  `pyproject.toml` run `pip install -e ".[test]"` then the full suite
  (`python -m pytest tests/`). A green PR CI is not sufficient — the merge
  commit itself must also pass locally and be pushed to BOTH remotes.
- **Merge locally, never on GitHub**: dependabot bot commits are unsigned
  and GitCode rejects them — `git merge` locally (GPG-signed) then
  `bash scripts/push-both.sh main`.
- **Before merging, run** `bash scripts/verify-deps-merge.sh <branch>`:
  diff-scope check + full-suite run when dependency files changed. The
  commit-msg hook rejects a dependabot merge that drags in non-dependency
  files (see `## Commit conventions` for its mechanics and bypass limits).
- **CI gate**: `.github/workflows/deps.yml` runs on any PR touching
  dependency files — enforces the dependency-only diff scope + full suite.
- **Allowed dependency files** (shared whitelist of hook / verify script /
  deps.yml, repo root only): `pyproject.toml`, `requirements*.txt`,
  `uv.lock`, `poetry.lock`. Anything else in a dependabot merge is a
  violation.

## Branching workflow (see `docs/workflow/branching.md`)

- **Semi-finished work never enters mainline** — commit it or branch it; never leave in-flight refactors in the working tree.
- **Open `feature/*` branches** for multi-Phase features, shared-module refactors, risky changes, or parallel agent work.
- **Double-green merge rule**: feature branch tests pass AND main tests pass → merge with `--no-ff`; discard = proposal rejected.
- **Keep merged branches for traceability**: after a `feature/*` branch is merged, DO NOT delete it. Retaining the branch (and its tip commit) lets a later review agent trace the full proposal — its commit series, decisions, and evolution — back from mainline. Delete only branches whose work was rejected, or after the review trail is no longer needed (e.g. archived in `docs/design/archive/reviews/`). If a branch was already deleted, its tip commit still exists in the object store — recover with `git branch <name> <tip-sha>` (visible via `git reflog`/`git log` of the merge commit) rather than treating it as lost.
- Check `git stash list` after interrupted commands (killed shells skip `git stash pop`).

## Parallel collaboration (see `docs/workflow/collaboration.md`)

- **Peer-level domain partition**: 7 work domains (K kernel / M memory / S sessions / T tools / C card-cell / B bus-services / A bridge-shell). Each agent owns exactly one domain and never edits files outside it without announcing.
- **Branch per agent**: `feature/<agent>-<area>`; merge order K → M/T/S → C/B → A.
- **Shared files register**: `l3.py`, `params/*.py`, `l3/boot/`, `tests/conftest.py`, `test_layer_imports.py`, `config/praxis.yaml` — one writer at a time; cross-domain API additions commit to main first.
- **Per-agent gates**: layer-import test + params-compliance test + domain tests + full baseline + ruff, all green before push.
- **One working tree per agent — use `git worktree` (FORBIDDEN to share a tree)**: `git worktree add <path> <branch>` gives each parallel agent a physically isolated directory (shared `.git`, zero cross-branch drift). Sharing one working tree across branches is FORBIDDEN: uncommitted changes follow `git checkout` and silently pollute the other branch. Two incidents on record: the network-refactor drift, and 2026-08-05 (an agent switched the shared main worktree to its feature branch, pulled an in-flight commit onto it, and merged — the commit only survived via reflog). Rules:
  - Each agent works in its own worktree: `git worktree add ../praxis-<area> feature/<agent>-<area>`.
  - **MUST run `bash scripts/check-worktree.sh` before any `git checkout`/`git switch`** — it rejects a dirty tree (exit 1) and duplicate checkouts of the same branch (exit 2). Never switch with a dirty tree; commit, stash, or commit as WIP first.
  - If dirty changes are found on the wrong branch, `git checkout <their-branch>` first so they follow back home, then commit/stash.
  - The `.githooks/post-checkout` hook warns when a switch carried a dirty tree along; treat the warning as a violation report, not an annoyance.
  - Clean up after merging: `git worktree remove <path>`; `git worktree list` shows all checkouts.

## Contract versioning (after the first branching milestone)

The first multi-agent branch confluence (2026-08: `feature/api-v2-prefix` +
`feature/skills-builtin-generalize` merged same-day) established the rules
below — treat them as load-bearing once any external consumer exists:

- **API contracts are versioned, not edited in place**: all HTTP routes live
  under `/api/v2/` (see `src/l4/api/api_routes.py`); breaking path changes
  require a new version segment (`/api/v3/`) plus an entry in the endpoint
  manifest (`src/l4/api/api_endpoints.py`). `_strip_version` already makes
  classification version-agnostic.
- **Path naming is enforced**: kebab-case segments, `{param}` placeholders
  whose names mirror handler keyword args (no generic `id`), no trailing-slash
  parameter style. `validate()` in `api_endpoints.py` rejects violations —
  run `python -m l4.api.api_endpoints` before pushing API changes.
- **The manifest is the single source of truth**: register new endpoints via
  `register_endpoint()` / `register_domain()` / `register_group()`; never
  hand-edit `API_ROUTES` for classification purposes.
- **Version bumps are atomic**: bump `pyproject.toml` version + `AGENTS.md`
  header + `docs/` SOC references in one commit; use patch for contract-safe
  additions, minor for API/behavior changes.

## Lint / format / typecheck (Makefile)

```bash
make test           # python tests/runner.py --batch 1 (same as test-fast)
make test-all       # both batches (runner.py)
make lint           # ruff check src/ tests/
make lint-fix       # ruff check --fix
make format         # ruff format src/ tests/
make format-check   # ruff format --check
make typecheck       # mypy src/ --no-namespace-packages --ignore-missing-imports --allow-untyped-calls --allow-untyped-decorators
make precommit       # pre-commit run --all-files
make hooks           # git config core.hooksPath .githooks
```

Ruff (line-length 120, double quotes) and mypy configs live in `pyproject.toml`; pre-commit hooks in `.pre-commit-config.yaml`.

**Two hook systems — know which one runs what:**
- `make hooks` installs the self-built bash hooks (`.githooks/`, set as `core.hooksPath`; the target also chmod +x the hooks, since `core.fileMode=false` clones silently lose the exec bit and git then skips the hook): `pre-commit` runs ruff over **staged `.py` files only** (see next bullet) + the size check (`scripts/pre-commit-size-check`; bulk commits >10k lines need `SKIP_SIZE_CHECK=1`) and the **mainline whitelist gate** (only `docs/ config/ locales/ .githooks/ scripts/` etc. may be committed directly on `main`; in-progress merges are exempt — they are the sanctioned double-green path; governance files `AGENTS.md` / `.github/` are not whitelisted by design — land them with `git commit --no-verify` on main or via a feature branch); `commit-msg` enforces English messages + `Co-Authored-By` + the dependabot merge gate (merge exemption triggers on a `Merge `/`Revert ` message prefix, so use git's default merge message — a hand-typed lowercase `merge:` message gets the full checks); `post-checkout` warns on dirty-tree branch switches. These are the load-bearing governance gates.
- **Ruff is staged-scoped, never whole-tree**: the pre-commit hook runs `ruff check --fix` (aborts the commit with `--exit-non-zero-on-fix` when it auto-fixes a staged file — re-stage and retry) and `ruff format --check` (rejects unformatted staged files — run `ruff format <files>` before staging) **only on the staged `.py` files**. A whole-tree pass would silently reformat files outside the commit and pollute the working tree on every commit — that was the 2026-08-07 format-debt incident (493 drifted files, now cleared and gated). Files outside the staged set are never touched, so the old `git checkout -- <unrelated files>` recovery and the `--no-verify` workaround for ruff are gone. If the hook rejects a commit, fix the STAGED files only.
- `make precommit` runs the pre-commit framework (`.pre-commit-config.yaml`: whitespace/EOF/YAML/JSON/large-file/merge-conflict/private-key checks + ruff + mypy). It is a style lint pass, NOT a governance gate — CI only runs its structural hooks (ruff/mypy are covered by dedicated steps).
- Don't rely on one system to do the other's job: a clean `pre-commit run` does not satisfy the mainline whitelist or commit-msg rules.

## Testing quirks

- **Singleton pollution**: Many services use global `_xxx = None` singletons. `tests/conftest.py` has an `autouse` fixture that resets ~33 known singletons before every test. When writing tests for new services, add their reset function to `_RESETS` in conftest.
- **Layer import test** (`test_layer_imports.py`) checks all `.py` files. New cross-layer imports must be allowlisted there.
- **Test dirs beyond `l1`–`l5`/`infra`**: `tests/integration/` (cross-layer, e.g. diff system, network transport, tool+agent) and `tests/benchmarks/` (bench_card.py). Both are picked up by plain `pytest` (auto-discovery).
- **Runner batches**: `tests/runner.py` splits into Batch 1 (fast core) and Batch 2 (slow extended, ~75s: r4_agent, convention, orchestration). `--batch 1|2` selects one. Note: `pyproject.toml` sets `addopts = "-n auto --dist loadfile"` (`testpaths = ["tests"]`, `pythonpath = ["src"]`), so plain `pytest` already parallelizes — the `-n 0` pins for infra/L1/L5 steps in `.github/workflows/test.yml` are explicit overrides, not the default.

## LLM config

Default: `ollama` / `qwen2.5-coder:7b` at `localhost:11434`. Configure via `config/praxis.yaml` or env vars (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_URL`, etc.).

## Project structure

| Path | Description |
|------|-------------|
| `config/praxis.yaml` | Main config (kernel, cell, LLM, constitution, gatechain, API) |
| `config/commands.yaml` | 49 L2 shell command definitions (plus code-registered `_cmd_*` handlers in `src/l2/l2_shell/commands/`) |
| `config/tools.yaml` | 72 tool definitions by ring layer |
| `.praxis-rules.md` | Constitution rules (parsed by `constitution.py`; repo root) |
| `config/praxis.yaml` `mcp:` | MCP server definitions |
| `locales/` | i18n: en, zh-CN, ja, ko |
| `memories/` | Runtime agent memory persistence |
| `config/skills/` | Builtin skills (read-only; loaded by `SkillManager.load_builtin`) |
| `.praxis/skills/` | Runtime skill artifacts: `evolved/` (project-scope evolved skills) + `lean/` (failure-trace cases) |
| `.github/agents/` | GitHub Agents definition (`assistant.agent.md`) — companion to `.github/workflows/`, not a build input |
| `docs/` | Architecture/config/design/workflow docs — entry points: `docs/configuration/overview.md`, `docs/workflow/branching.md` |

## Key files

- `src/main.py` — CLI entry: `python main.py <boot|health|ps|card|tools|audit|chain|interrupts|devices|status>`
- `src/l5/cli.py` — CLI command implementations
- `src/l1/kernel/os.py` — OS lifecycle (boot/shutdown/restart/watchdog)
- `src/l1/kernel/constitution.py` — Constitutional rules engine (highest authority)
- `src/l3/tool_system/tool_pipeline.py` — 9-step tool execution pipeline
- `src/l3/card/card_registry.py` — Card lifecycle management
- `src/l3/boot/boot.py` — 7-step system bootstrap
- `src/l3/boot/lifecycle.py` — Factory reset, singleton reset, disk wipe
- `src/l3/cell/peers/l3a/` — **L3A session system (20 modules):** `__init__` (daemon+singleton), `session` (Session/Manager), `session_history` (Page/Message/SessionHistory model), `session_ask` (ask-state), `session_compress` (transcript compression), `session_prompt` (prompt assembly), `subagent` (L3ASubAgentPool), `summaries` (summary+R4 glue), `context` (ContextEpoch/Registry), `inbox` (PromptInbox), `model` (L3AModelConfig), `archive` (R4 store/restore), `pipeline` (ManagedToolOutput), `task_table` (task monitor), `helpers` (cardwrite/convergence), `api` (L2 routing), `agents_md` (AGENTS.md generator), `types` (enums/dataclasses), `params` (constants), `ask` (clarification state machine)
- `src/l3/cell/peers/l3.py` — CentralController (L3A+L3B+CardRegistry)

## Sandbox / Structured Diff System

- **Per-hunk attribution**: each sandbox entry records `agent_id`,
  `tool_name`, `task_id`, `modified_at` (ISO 8601) per hunk — every edit is
  attributable.
- **Multi-agent entries**: keyed by `path::agent_id`; parallel agents can
  edit the same file independently, and the sandbox returns all entries for
  a path so cross-review sees every parallel edit.
- **Summary cache (L1→L3)**: in-memory per-entry stats → Cell-level shared
  cache → persistent `.praxis_sandbox_state.json`.
- **Diff views**: `agent` (attribution), `human` (readable), `summary`
  (stats-only), `colored` (semantic colorization). Colors configurable via
  `config/praxis.yaml` `diff.colors` (see `docs/architecture/` for the
  scheme); API: `POST /api/v2/diff/colors` get/set/reset.
- **Flow**: agent writes → entry with per-hunk attribution → cross-review
  reads all entries for the file → message shows who changed what, with
  which tool, and when.
