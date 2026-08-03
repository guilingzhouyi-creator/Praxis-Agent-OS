# Development Workflow — Lightweight Branching

> Status: active | Applies to all collaborators (humans and agent tools)

Praxis is a multi-writer repository (user + OpenCode / AtomCode / Copilot).
The project reached the branching critical point when an in-flight refactor
(tool_spec) left the working tree half-modified and broke the full test
suite — the mainline lost "always shippable" status. This document defines
the lightweight branching policy that keeps mainline green while multiple
writers and large refactors coexist.

## 1. Core principle

**Semi-finished work never enters mainline.**

Working-tree changes must be either committed or moved to a feature branch.
Half-finished code left in the working tree poisons test verification for
every collaborator.

## 2. Branch model (lightweight, governance-flavored)

```
main          stable, shippable, tests green          ("已生效法律")
feature/*     proposal branch for big changes/refactors ("立法提案")
small changes commit directly to main                  (bug fixes, docs, tests)
```

### Mapping to Praxis governance

| Git concept | Praxis governance |
|-------------|-------------------|
| feature branch | Card in `proposed` state |
| double-green verification | CONFERENCE deliberation (convergence) |
| merge to main | card `approved` (legislation passed) |
| discard branch | proposal rejected (zero pollution) |
| git revert | legislation repeal |

## 3. When to branch

Open a `feature/<name>` branch when ANY of:

- multi-Phase feature work (e.g. the R5 memory-graph build-out)
- refactors touching shared modules (kernel, tool registry, config, memory)
- any change that cannot be verified green in one session
- parallel work by multiple agent tools on overlapping areas
- risky changes (gatechain, L1 kernel, persistence)

Commit directly to main only for:

- single-file bug fixes
- documentation / config tweaks
- test additions that do not change behavior

## 4. Double-green merge rule

A feature branch may merge to main only when:

1. `python -m pytest tests/ -q` passes **on the branch**, and
2. the same suite passes **on main** (baseline check), and
3. commits carry English messages + `Co-Authored-By` (commit-msg hook).

Merge with `--no-ff` to preserve the proposal record.

## 5. Working-tree hygiene (iron rule)

- Never leave in-flight refactors in the working tree.
- If a change cannot be finished and committed now: `git stash` it **and
  note it** (stash entries get lost when shells are killed), or open a
  branch and commit WIP.
- Check `git stash list` after any interrupted command (killed shells
  skip `git stash pop` — see the R5 Phase-3 incident).

## 6. Mainline protection

- `main` must always pass: `python -m pytest tests/ -q` (or the documented
  batch splits) before push.
- After large branch merges, verify `git log origin/main..HEAD` before push.
- Release points: tag `main` (e.g. `v0.4.x`).

## 7. Enforcement

- `.githooks/commit-msg` — English messages + Co-Authored-By (already active)
- `.githooks/pre-commit` — ruff + format + size check (already active)
- Branch hygiene is convention-based; the double-green rule is enforced by
  the verifier in the loop (agent collaborators read this document via
  AGENTS.md).
