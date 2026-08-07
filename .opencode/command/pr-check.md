---
description: Review a pending commit, feature branch, or PR against the Praxis checklist (English commits, Co-Authored-By trailer, dual-remote push, branch/worktree workflow). Use /pr-check before merge or push.
---

Review the pending changes against the Praxis PR checklist.

## Gather Context

Run these git commands to build the review context:
- `git status` and `git log --oneline -5` — what is pending.
- `git diff HEAD~1` (or the merge/PR diff) — the change set.
- `git log -1 --format=%B` — the commit message under review.
- `git branch --show-current` — which branch we are on.

## Checklist

### Commit message (enforced by `.githooks/commit-msg`)
- [ ] Message written in English (CJK characters are rejected)
- [ ] Conventional Commits format (`feat:` / `fix:` / `docs:` / `refactor:` / `chore:` ...)
- [ ] `Co-Authored-By` trailer present (exempt: merge/revert commits, `--amend`)

### Verification gates
- [ ] Full test suite passes: `python -m pytest tests/ -x -q`
- [ ] Ruff clean: `make lint` (double quotes, line-length 120)
- [ ] Layer import test passes: `python -m pytest tests/infra/test_layer_imports.py -x -q`
- [ ] Params compliance passes: `python -m pytest tests/infra/test_params_compliance.py -x -q`
- [ ] No hardcoded magic numbers — use `src/l1/kernel/params/` constants
- [ ] Truncation/hash/importance literals use the `params/system.py` / `params/tool.py` constants

### API contract (if API changed)
- [ ] Routes under `/api/v2/` (breaking changes require `/api/v3/` + manifest entry)
- [ ] Manifest validated: `python -m l4.api.api_endpoints`

### Workflow
- [ ] `bash scripts/check-worktree.sh` run before any `git checkout`/`git switch`
- [ ] Push to BOTH remotes: `git push origin main; git push github main`
- [ ] Feature branch double-green: branch tests AND main tests pass before merge
- [ ] Merged `feature/*` branch retained (do not delete — traceability)

For each item, mark pass or fail with a one-line explanation. Report the failures first, then the full pass/fail summary.
