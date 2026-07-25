---
name: project-conventions
description: NOMOS Praxis project conventions — code style, patterns, and architecture rules. Apply automatically when writing or reviewing code.
user-invocable: false
---

## NOMOS Praxis — Project Conventions

### Naming Conventions
- Modules: `snake_case.py` (e.g. `execution_engine.py`, `fault_tolerance.py`)
- Classes: `PascalCase` (e.g. `ProcessControlBlock`, `AgentTerminal`, `HTNPlanner`)
- Functions/methods: `snake_case` (e.g. `get_allocator`, `register_syscall`, `dispatch_card`)
- Constants: `UPPER_SNAKE_CASE` with `Final` type hint (e.g. `MUTEX_DEFAULT_TIMEOUT: Final[float] = 30.0`)
- Private module-level: `_underscore_prefix` (e.g. `_audit_log`, `_SYSCALL_REGISTRY`)
- Type variables: short PascalCase (e.g. `T`, `R`)

### Architecture Patterns
- **Kernel syscall dispatch**: All kernel operations go through `syscall(op, *args, **kwargs) -> dict`. Every call is audited, structured error codes returned.
- **Singleton accessors**: Kernel primitives use `get_*()` factory functions (e.g. `get_mutex()`, `get_semaphore()`, `get_allocator()`)
- **Process architecture**: Each `AgentTerminal` registers as a `PCB` (Process Control Block) in the kernel process table.
- **Service layer**: Organized in `src/services/` — each service is a self-contained module with clear boundaries.
- **Card-based execution**: Work is packaged as "cards" dispatched through the cell system.

### Coding Standards
- **Module docstring**: Every `.py` file has a docstring describing its purpose and architecture.
- **Imports order**: stdlib → third-party → local (with blank line separators)
- **Logger**: `logger = logging.getLogger(__name__)` at module level
- **Thread safety**: Use `threading.Lock()` with context manager (`with lock:`)
- **Error handling**: Return structured dicts `{"success": bool, "error": str, ...}` rather than raising exceptions for expected failures.
- **Type hints**: Use `from __future__ import annotations` and full type hints on all public functions.
- **Dataclasses**: Use `@dataclass` for configuration objects and data transfer objects.
- **Enums**: Use `from enum import Enum, auto` with `auto()` for state machines (e.g. `ProcessState`, `GateStatus`).

### File Organization
- `src/kernel/` — Core OS primitives (syscall, allocator, process table, sync primitives, VFS, IPC)
- `src/services/` — Higher-level services (terminal, cell, planner, sandbox, LLM, LSP, etc.)
- `src/tools/` — Tool implementations organized by category (base, advanced, cell, special)
- `tests/` — pytest tests: `test_*.py` files, `testpaths = ["tests"]`
- Config constants go in `kernel/params.py` — the single source of truth; re-export via `constants.py`

### Forbidden
- No bare `except:` — always specify exception types
- No mutable default arguments in function signatures
- No `print()` in production code — use `logger`
- No hardcoded magic numbers in kernel logic — define in `params.py` first
- No synchronous blocking I/O in hot paths

### LLM Integration
- Provider-agnostic design: switch via `praxis.yaml` config (`provider: ollama | openai | anthropic | mock`)
- Rate limiting via token bucket / `rate_limit` config
- Temperature and max_tokens controlled per-call, with file-level defaults

### Testing
- Use pytest with `pyproject.toml` config section `[tool.pytest.ini_options]`
- Integration tests in `test_*.py` matching pattern `test_*.py`
- YAML fixture files for test scenarios (e.g. `snake_card.yaml`, `self_bootstrap.yaml`)
