---
description: Discover uncovered code paths in a Praxis source file and generate pytest tests for them. Use /test-writer <source_file> to raise coverage.
---

Analyze the source file `$ARGUMENTS`, identify uncovered code paths, and generate pytest tests matching Praxis conventions.

## Workflow

### 1. Analyze Source File

Read the target file at `$ARGUMENTS`. Identify:
- All public classes, functions, and methods.
- Input parameters, return types, and error paths.
- Conditional branches and edge cases.

### 2. Match Project Conventions

Reference existing test files (`tests/**/test_*.py`) for style patterns:
- `from __future__ import annotations` at top.
- Imports resolve from `src/` via `pythonpath = ["src"]` in `pyproject.toml` — no `sys.path` manipulation.
- Class-based grouping: `class TestFoo:`.
- Plain `assert` statements (no `self.assertEqual`).
- `tests/conftest.py` autouse fixtures handle singleton resets.

### 3. Generate Tests

Cover:
- Normal/positive paths.
- Boundary conditions.
- Error paths and exception handling.
- Edge cases in conditional logic.

### 4. Write Test File

Map source to test path:
- `src/l1/kernel/foo.py` → `tests/l1/test_foo.py`
- `src/l2/foo.py` → `tests/l2/test_foo.py`
- `src/l3/foo.py` → `tests/l3/test_foo.py`
- `src/l4/foo.py` → `tests/l4/test_foo.py`
- etc.

If the test file already exists, append new tests rather than overwriting.

### 5. Verify

Run `python -m pytest <test_file> -x -q --tb=short`. If any tests fail, diagnose and fix before reporting completion.
