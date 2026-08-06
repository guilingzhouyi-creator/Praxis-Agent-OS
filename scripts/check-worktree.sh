#!/usr/bin/env bash
# Worktree discipline checker — run BEFORE any branch switch.
#
# Every parallel agent MUST work in its own `git worktree`. Sharing a single
# working tree across branches is FORBIDDEN: uncommitted changes follow
# `git checkout` and silently pollute the other branch (see the 2026-08-05
# shared-worktree drift incident — a commit landed on the wrong branch and
# was only recovered via reflog).
#
# Usage:
#   bash scripts/check-worktree.sh [branch]        # verify current checkout
#   bash scripts/check-worktree.sh                 # report current state
#   bash scripts/check-worktree.sh --allow-dirty   # report but tolerate a dirty
#                                                  # tree (escape hatch for
#                                                  # deliberate shared-tree ops)
#
# Exit codes:
#   0 — clean / correct
#   1 — dirty tree (commit, stash, or move to the right branch first)
#   2 — branch checked out in more than one worktree
#   3 — other violation (branch expected but not current)

set -u

ALLOW_DIRTY=0
EXPECTED_BRANCH=""
for arg in "$@"; do
  case "$arg" in
    --allow-dirty) ALLOW_DIRTY=1 ;;
    -*) echo "[worktree-check] unknown option: $arg" >&2; exit 3 ;;
    *) EXPECTED_BRANCH="$arg" ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[worktree-check] not inside a git repository" >&2
  exit 3
}

CURRENT="$(git branch --show-current 2>/dev/null)"
DIRTY="$(git status --porcelain 2>/dev/null | head -20)"
EXIT=0

echo "[worktree-check] current branch: ${CURRENT:-<detached>}"
echo "[worktree-check] top-level:      $ROOT"

# 1. Dirty tree — the classic drift vector.
if [ -n "$DIRTY" ]; then
  if [ "$ALLOW_DIRTY" -eq 1 ]; then
    echo "[worktree-check] WARN: working tree is dirty (--allow-dirty given)"
    echo "$DIRTY" | sed 's/^/    /'
  else
    echo "[worktree-check] ERROR: working tree is dirty — uncommitted changes"
    echo "[worktree-check] would follow a branch switch and pollute the target."
    echo "$DIRTY" | sed 's/^/    /'
    echo "[worktree-check] FIX: commit, stash, or checkout the owning branch first."
    echo "[worktree-check] (deliberate shared-tree op? re-run with --allow-dirty)"
    EXIT=1
  fi
fi

# 2. Duplicate checkout — the same branch in two worktrees.
DUPS="$(git worktree list --porcelain 2>/dev/null | awk -v b="${CURRENT:-}" '
  /^worktree / { w=$2 }
  /^branch / {
    split($0, a, " "); br=substr(a[2], 12)
    if (br == b) { print w }
  }' | wc -l)"
if [ "${DUPS:-0}" -gt 1 ]; then
  echo "[worktree-check] ERROR: branch '${CURRENT:-}' is checked out in more"
  echo "[worktree-check] than one worktree — parallel agents must each use"
  echo "[worktree-check] their own branch."
  git worktree list
  EXIT=2
fi

# 3. Expected branch mismatch.
if [ -n "$EXPECTED_BRANCH" ] && [ "${CURRENT:-}" != "$EXPECTED_BRANCH" ]; then
  echo "[worktree-check] ERROR: expected branch '$EXPECTED_BRANCH' but current is '${CURRENT:-}'."
  EXIT=3
fi

if [ "$EXIT" -eq 0 ]; then
  echo "[worktree-check] OK — safe to switch."
fi
exit "$EXIT"
