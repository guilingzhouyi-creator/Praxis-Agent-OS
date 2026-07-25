---
name: code-reviewer
description: Automated code quality review for NOMOS Praxis. Runs in parallel to review kernel/services code against project conventions.
allowed-tools: Read, Grep, Glob, Bash
---

## Code Review Focus Areas

### Architecture & Design
- Are syscall patterns followed consistently? (All kernel ops through `syscall()`)
- Is the service boundary respected? (kernel/ vs services/ separation)
- Are there circular dependencies between modules?
- Are singleton accessors (`get_*()`) used correctly?

### Code Quality
- Does the code follow naming conventions (snake_case functions, PascalCase classes, UPPER_SNAKE_CASE constants)?
- Are all public functions properly typed with full type hints?
- Are mutable default arguments avoided?
- Are bare `except:` clauses avoided?
- Are magic numbers defined in `params.py` rather than hardcoded?

### Thread Safety
- Are shared resources protected with `threading.Lock()`?
- Is `with lock:` context manager used consistently?
- Are there potential deadlocks or race conditions?

### Error Handling
- Are structured dict returns (`{"success": bool, "error": str}`) used for expected failures?
- Are exceptions raised only for truly exceptional conditions?
- Is `logger.error()` used instead of `print()`?

### Testing
- Does new code have corresponding tests in `tests/`?
- Are tests using pytest patterns?
- Are YAML fixtures used for complex test scenarios?

### Checklist
- [ ] Architecture follows kernel syscall / service layer pattern
- [ ] No circular dependencies introduced
- [ ] Naming conventions followed (snake_case, PascalCase, UPPER_SNAKE_CASE)
- [ ] Full type hints on all public functions
- [ ] Thread safety: locks on shared state, no mutable defaults
- [ ] Structured error returns, not bare exceptions
- [ ] No hardcoded magic numbers — use params.py
- [ ] Corresponding tests exist
- [ ] Logger used instead of print
- [ ] Module docstring present
