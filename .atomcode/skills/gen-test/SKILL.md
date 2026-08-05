---
name: gen-test
description: Generate tests for a source file following NOMOS Praxis project conventions. Use when asked to write tests or add coverage.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Bash
---

## Overview

Generates pytest tests for a given source file following NOMOS Praxis conventions. Handles singleton reset patterns, conftest fixtures, and the project's layer-based architecture.

## When to Use

Invoke via `/gen-test <source_file>` when:
- Adding a new source file that needs test coverage.
- Asked to increase test coverage for a specific module.
- Writing tests for a bug fix or new feature.

## Workflow

### 1. Read Source File

Read the source file at `$ARGUMENTS`. Identify public classes, functions, and methods.

### 2. Determine Test File Path

Map source to test path:
- `src/l1/kernel/foo.py` → `tests/l1/test_foo.py`
- `src/l2/foo.py` → `tests/l2/test_foo.py`
- `src/l3/foo.py` → `tests/l3/test_foo.py`
- etc.

### 3. Generate Tests

Apply project test patterns:

```python
"""Tests for <module>."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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

Coverage targets:
- Normal/positive paths.
- Error/edge cases where applicable.
- Lifecycle (init → use → cleanup) for services with start/stop.

### 4. Write and Verify

Write the test file. Run `python -m pytest <test_file> -x -q --tb=short`. Fix any failures.

## Conventions

- **Singleton reset**: `conftest.py` handles `_reset_singletons` automatically via `autouse` fixture — no manual reset in tests.
- **Class-based grouping**: `class TestFoo:`.
- **Plain assert**: `assert result["success"] is True` — no `self.assertEqual()`.
- **Direct instantiation**: Test parameters passed directly (e.g., `ApiGateway(port=18081, auth_token="")`).
- **Lifecycle cleanup**: For services with start/stop, call `stop_xxx()` in the same test.