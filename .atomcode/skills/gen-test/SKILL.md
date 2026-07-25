---
name: gen-test
description: Generate tests for a source file following NOMOS Praxis project conventions. Use when asked to write tests or add coverage.
disable-model-invocation: true
---

## Context
- Source file: $ARGUMENTS
- Project conventions: pytest, class-based tests, `from __future__ import annotations`
- Singleton reset: conftest.py handles `_reset_singletons` automatically via autouse fixture

## Test Patterns (NOMOS Praxis)

### Structure
- Tests go in `tests/` directory matching the module name: `src/services/foo.py` → `tests/test_foo.py`
- Use class-based grouping: `class TestFoo:`
- Use `from __future__ import annotations` at top
- Add `sys.path.insert(0, ...)` to import from `src/`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
```

### Imports
- Import directly from the module under test (no conftest imports needed for function access)
- Example: `from services.api_gateway import ApiGateway`

### Patterns Observed in the Codebase
- Test methods are plain `def test_xxx(self):` (no fixtures unless needed)
- Direct instantiation with test parameters (e.g., `ApiGateway(port=18081, auth_token="")`)
- Assertions use plain `assert` statements
- For services with start/stop lifecycle, call `stop_xxx()` in the same test
- Test listing/iteration endpoints by checking string membership in results

### Steps
1. Read the source file at $ARGUMENTS
2. Identify public classes, functions, and methods
3. Generate tests covering:
   - Normal/positive paths
   - Error/edge cases where applicable
   - Lifecycle (init → use → cleanup)
4. Write the test file to `tests/test_<module>.py`
5. Report the file created and coverage estimate
