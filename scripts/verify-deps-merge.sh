#!/usr/bin/env bash
# Dependency-merge verifier — run BEFORE merging a dependabot branch.
#
# Enforces AGENTS.md "Dependency management": a dependency bump must be
# validated locally before merge — the merge commit itself must pass the
# full suite, not just the PR CI.
#
# Usage:
#   bash scripts/verify-deps-merge.sh <branch>   # e.g. dependabot/pip/pyyaml-*
#   bash scripts/verify-deps-merge.sh            # verify the current checkout
#
# Exit codes:
#   0 — safe to merge (dependency-only diff, full suite green when deps changed)
#   1 — diff scope violation (non-dependency files present)
#   2 — dependency change present but the full test suite failed
#   3 — usage / branch resolution error

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[verify-deps-merge] ERROR: not inside a git repository" >&2
  exit 3
}
cd "$ROOT"

MAIN_BASE="${MAIN_BASE:-main}"
BRANCH="${1:-}"
MERGE_MODE=0
if [ -z "$BRANCH" ]; then
  BRANCH="$(git branch --show-current 2>/dev/null || true)"
  # Detached HEAD on a fresh merge commit: verify the merge-introduced diff.
  if [ -z "$BRANCH" ] && git rev-parse HEAD^2 >/dev/null 2>&1; then
    BRANCH="HEAD"
    MERGE_MODE=1
    echo "[verify-deps-merge] detached HEAD is a merge commit — verifying merge diff."
  fi
fi
if [ -z "$BRANCH" ] || ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "[verify-deps-merge] ERROR: cannot resolve branch '$BRANCH'" >&2
  echo "[verify-deps-merge] usage: bash scripts/verify-deps-merge.sh <branch>" >&2
  exit 3
fi

echo "[verify-deps-merge] branch: $BRANCH (base: $MAIN_BASE)"

# ── 1. Diff scope: dependency files only ──────────────────────────────────
DEP_FILES_RE='^(pyproject\.toml|requirements[^/]*\.txt|uv\.lock|poetry\.lock)$'
if [ "$MERGE_MODE" = "1" ]; then
  CHANGED="$(git diff --name-only HEAD^1 HEAD^2 2>/dev/null || true)"
else
  CHANGED="$(git diff --name-only "$MAIN_BASE"..."$BRANCH" 2>/dev/null || \
            git diff --name-only "$MAIN_BASE" "$BRANCH" 2>/dev/null || true)"
fi
if [ -z "$CHANGED" ]; then
  echo "[verify-deps-merge] INFO: no diff vs $MAIN_BASE — nothing to verify."
  exit 0
fi

VIOLATIONS="$(printf '%s\n' "$CHANGED" | grep -vE "$DEP_FILES_RE" || true)"
if [ -n "$VIOLATIONS" ]; then
  echo "[verify-deps-merge] ❌ NON-DEPENDENCY FILES in diff:" >&2
  printf '%s\n' "$VIOLATIONS" | sed 's/^/     ✗ /' >&2
  echo "[verify-deps-merge]    Dependabot merges may only touch dependency files." >&2
  echo "[verify-deps-merge]    Split code changes into a feature branch." >&2
  exit 1
fi

echo "[verify-deps-merge] ✅ diff scope OK (dependency files only):"
printf '%s\n' "$CHANGED" | sed 's/^/     /'

# ── 2. Full suite when pyproject.toml changed ─────────────────────────────
if printf '%s\n' "$CHANGED" | grep -qE '^(pyproject\.toml|requirements[^/]*\.txt|uv\.lock|poetry\.lock)$'; then
  echo "[verify-deps-merge] dependency files changed — running full suite..."
  if ! python -m pytest tests/ -q --tb=short; then
    echo "[verify-deps-merge] ❌ FULL SUITE FAILED — do not merge." >&2
    exit 2
  fi
  echo "[verify-deps-merge] ✅ full suite green."
else
  echo "[verify-deps-merge] INFO: no dependency manifest change — suite skipped."
fi

echo "[verify-deps-merge] OK — safe to merge. Push BOTH remotes afterwards:"
echo "    bash scripts/push-both.sh main"
exit 0
