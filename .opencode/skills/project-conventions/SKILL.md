---
name: project-conventions
description: Use when writing or reviewing Praxis code to recall project conventions — naming, layer import rules, params constants governance, three-layer config, coding standards. Front-loads the rules the repo enforces.
---

## Overview

Background knowledge skill for the Praxis Agent OS. Applies these conventions automatically when writing or reviewing code. No user invocation needed — AGENTS.md is the authoritative reference; this skill is the condensed recap.

## Naming Conventions

- **Modules**: `snake_case.py` (e.g. `execution_engine.py`, `fault_tolerance.py`)
- **Classes**: `PascalCase` (e.g. `ProcessControlBlock`, `AgentTerminal`, `HTNPlanner`)
- **Functions/methods**: `snake_case` (e.g. `get_allocator`, `register_syscall`, `dispatch_card`)
- **Constants**: `UPPER_SNAKE_CASE` with `Final` type hint (e.g. `MUTEX_DEFAULT_TIMEOUT: Final[float] = 30.0`)
- **Private module-level**: `_underscore_prefix` (e.g. `_audit_log`, `_SYSCALL_REGISTRY`)
- **Type variables**: short PascalCase (e.g. `T`, `R`)

## Architecture Patterns

- **Kernel syscall dispatch**: All kernel operations go through `syscall(op, *args, **kwargs) -> dict` (defined in `src/l1/kernel/__init__.py`). Every call is audited, structured error codes returned.
- **Singleton accessors**: Kernel primitives use `get_*()` factory functions (e.g. `get_mutex()`, `get_semaphore()`, `get_allocator()`).
- **Process architecture**: Each `AgentTerminal` registers as a `PCB` (Process Control Block) in the kernel process table.
- **Service layer**: Organized in `src/l3/` and `src/l4/` — each service is a self-contained module with clear boundaries.
- **Card-based execution**: Work is packaged as "cards" dispatched through the cell system.
- **Layer import rules**: L5 → L4/L3/L2/L1; L4 → L3/L2/L1; L3 → L2/L1; L2 → L1 only; L1 cannot import upper layers. Enforced by `tests/infra/test_layer_imports.py` (93 pre-existing cross-layer imports allowlisted).

## Coding Standards

- **Module docstring**: Every `.py` file has a docstring describing its purpose.
- **Imports order**: stdlib → third-party → local (with blank line separators)
- **Logger**: `logger = logging.getLogger(__name__)` at module level
- **Thread safety**: Use `threading.RLock()` with context manager (`with lock:`) — reentrant locks preferred.
- **Error handling**: Return structured dicts `{"success": bool, "error": str, ...}` rather than raising exceptions for expected failures.
- **Type hints**: Use `from __future__ import annotations` and full type hints on all public functions.
- **Dataclasses**: Use `@dataclass` for configuration objects and data transfer objects.
- **Enums**: Use `from enum import Enum, auto` with `auto()` for state machines (e.g. `ProcessState`, `GateStatus`).
- **Strings**: Double quotes for strings (ruff `quote-style = "double"`), line-length 120.
- **No bare `except:`**: Use `except Exception:`.

## File Organization

```
src/l5/       — User layer: CLI, agent runtime
src/l4/       — Bridge: API gateway, LLM engine, sandbox, MCP, vault
src/l3/       — Cell layer: agents, memory, cards, scheduler, tool pipeline
src/l2/       — Shell: 49 YAML commands + code-registered _cmd_* handlers, i18n, agent selector
src/l1/kernel/ — Kernel primitives: sync, event, allocator, gatechain, VFS, IPC
src/l1/kernel/params/ — ~1,000 constants across 8 sub-modules
tests/        — pytest tests: test_*.py files
config/       — praxis.yaml, commands.yaml, tools.yaml, discovery/, skills/
```

## Config Constants

- **All magic numbers go in `src/l1/kernel/params/`** — never hardcode in implementation files.
- **New kernel modules** must be exported in `kernel/__init__.py` `__all__`.
- **New config items** register defaults in `kernel/settings.py` `DEFAULTS`.
- **Three-layer config**: `params/*.py` (compile-time defaults) ← `config/discovery/*.yaml` (structural overrides) ← `config/praxis.yaml` (deployment config).

## Truncation & Hash Constants

- **Truncation literals**: Use `LOG_TRUNC_*` constants from `params/system.py` (`LOG_TRUNC_40` through `LOG_TRUNC_10000`). Never write `[:40]`, `[:3000]` etc. directly.
- **Hash truncation**: Use `HASH_TRUNC_SHORT` (8), `HASH_TRUNC_MEDIUM` (12), `HASH_TRUNC_LONG` (16).
- **Memory importance weights**: Use `MEMORY_IMPORTANCE_*` and `MEMORY_PRESSURE_*` constants from `params/system.py`.
- **Timeout defaults**: Reference `params/tool.py` or `params/system.py` constants, not raw numbers.
- **File path strings**: Centralize in `params/system.py` or `paths.py`. Avoid `"*.json"`, `"foo/bar.yaml"` in implementation code.
- **Package manager timeouts**: Use `TOOL_PACKAGE_MANAGER_TIMEOUT`, `TOOL_PIP_INSTALL_TIMEOUT`, etc. from `params/tool.py`.

## Forbidden

- No bare `except:` — always specify exception types.
- No mutable default arguments in function signatures.
- No `print()` in production code — use `logger`.
- No hardcoded magic numbers — define in `params/` first.
- No synchronous blocking I/O in hot paths.
- Never import `services/` inside `kernel/` — one-way dependency.
- Never use `sed`/`awk`/`perl -i` to edit source files — use `edit_file` or `write_file`.
- No CJK in comments/docstrings — English is the baseline language (i18n translation data excepted).

## Testing

- Use pytest with `pyproject.toml` config section `[tool.pytest.ini_options]` (`addopts = "-n auto --dist loadfile"`, `pythonpath = ["src"]`).
- Tests in `tests/` matching `test_*.py` (subdirs `l1`–`l5`, `infra`, `integration`, `benchmarks`).
- Singleton pollution: `tests/conftest.py` resets ~33 known singletons via an `autouse` fixture.
- Layer import test (`test_layer_imports.py`) checks all `.py` files.
- New cross-layer imports must be allowlisted in `test_layer_imports.py`.
