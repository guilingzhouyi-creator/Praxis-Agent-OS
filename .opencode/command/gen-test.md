---
description: Generate pytest tests for a Praxis source file following project conventions. Use /gen-test <source_file> when adding a new file that needs coverage or extending existing tests.
---

Generate pytest tests for the source file `$ARGUMENTS` following Praxis conventions.

## Workflow

### 1. Read Source File

Read the source file at `$ARGUMENTS`. Identify public classes, functions, and methods.

### 2. Determine Test File Path

Map source to test path:
- `src/l1/kernel/foo.py` → `tests/l1/test_foo.py`
- `src/l2/foo.py` → `tests/l2/test_foo.py`
- `src/l3/foo.py` → `tests/l3/test_foo.py`
- `src/l4/foo.py` → `tests/l4/test_foo.py`
- etc.

If the test file already exists, append new tests rather than overwriting.

### 3. Generate Tests

Apply project test patterns:

```python
"""Tests for <module>."""

from __future__ import annotations

from <module> import <Class>


class Test<Class>:
    """Test suite for <Class>."""

    def test_<positive_case>(self):
        """<What this test verifies>."""
        instance = <Class>(<test_params>)
        result = instance.<method>()
        assert result["success"] is True

    def test_<error_case>(self):
        """<What this test verifies>."""
        instance = <Class>(<test_params>)
        result = instance.<method>()
        assert result["success"] is False
```

Notes:
- Imports resolve from `src/` via `pythonpath = ["src"]` in `pyproject.toml` — no `sys.path` manipulation needed.
- Coverage targets: normal/positive paths, error/edge cases, lifecycle (init → use → cleanup) for services with start/stop.
- `tests/conftest.py` resets singletons automatically via an `autouse` fixture — no manual reset in tests.

### 4. Write and Verify

Write the test file. Run `python -m pytest <test_file> -x -q --tb=short`. Fix any failures.

## Conventions

- **Singleton reset**: handled by the `autouse` fixture in `tests/conftest.py`.
- **Class-based grouping**: `class TestFoo:`.
- **Plain assert**: `assert result["success"] is True` — no `self.assertEqual()`.
- **Lifecycle cleanup**: for services with start/stop, call `stop_xxx()` in the same test.
