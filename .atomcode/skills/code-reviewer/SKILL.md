---
name: code-reviewer
description: Automated code quality review for NOMOS Praxis. Runs in parallel to review kernel/services code against project conventions.
allowed-tools: Read, Grep, Glob, Bash
---

## Overview

Parallel code quality reviewer for the Praxis codebase. Triggered automatically on code changes to review architecture, code quality, thread safety, error handling, and test coverage.

## Workflow

### 1. Scan Changed Files
Identify files in the change set. Prioritize kernel (`src/l1/kernel/`), cell (`src/l3/`), bridge (`src/l4/`), and shell (`src/l2/`) layers.

### 2. Architecture & Design Review
- Verify syscall patterns are followed consistently (all kernel ops through `syscall()`).
- Check service boundary is respected (L1-L5 layer separation per import rules).
- Detect circular dependencies between modules.
- Verify singleton accessors (`get_*()`) are used correctly.

### 3. Code Quality Review
- Check naming conventions: snake_case functions, PascalCase classes, UPPER_SNAKE_CASE constants.
- Verify full type hints on all public functions.
- Confirm no mutable default arguments.
- Check no bare `except:` clauses.
- Verify magic numbers are defined in `params/` rather than hardcoded.
- Confirm double quotes for strings, line-length ≤ 120.

### 4. Thread Safety Review
- Verify shared resources protected with `threading.RLock()`.
- Confirm `with lock:` context manager used consistently.
- Identify potential deadlocks or race conditions.

### 5. Error Handling Review
- Verify structured dict returns (`{"success": bool, "error": str}`) for expected failures.
- Confirm exceptions raised only for truly exceptional conditions.
- Check `logger.error()` used instead of `print()`.

### 6. Testing Review
- Verify new code has corresponding tests in `tests/`.
- Confirm tests use pytest patterns.
- Check YAML fixtures used for complex test scenarios.

## Checklist

- [ ] Architecture follows kernel syscall / service layer pattern
- [ ] No circular dependencies introduced
- [ ] Layer import rules respected (L5→L4→L3→L2→L1 only)
- [ ] Naming conventions followed (snake_case, PascalCase, UPPER_SNAKE_CASE)
- [ ] Full type hints on all public functions
- [ ] Thread safety: reentrant locks on shared state, no mutable defaults
- [ ] Structured error returns, not bare exceptions
- [ ] No hardcoded magic numbers — use params/
- [ ] Double quotes, line-length ≤ 120
- [ ] Corresponding tests exist
- [ ] Logger used instead of print
- [ ] Module docstring present