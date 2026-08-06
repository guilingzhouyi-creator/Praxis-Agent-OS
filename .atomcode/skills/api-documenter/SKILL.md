---
name: api-documenter
description: Automated review of API documentation completeness and consistency for NOMOS Praxis. Runs on code changes affecting API routes and handlers.
user-invocable: false
allowed-tools: Read, Grep, Glob
---

## Overview

Automated API documentation reviewer for the Praxis codebase. Runs in the background when API route or handler files change, comparing registered routes against documentation to flag gaps and inconsistencies.

## When to Run

Review is triggered automatically when files matching these patterns change:
- `src/l4/api/api_routes.py`
- `src/l4/api/api_gateway.py`
- `src/l4/api/api_handlers*.py`
- `src/l4/api_handlers/api_handlers_*.py`
- `docs/api-reference.md` or `docs/design/*.md`

## Workflow

### 1. Scan Routes

Read `src/l4/api/api_routes.py` and `src/l4/api/api_gateway.py` to find all registered routes. Extract:
- HTTP method
- URL path
- Handler function reference
- Route description (if any)

### 2. Check Handlers

For each route, read the handler function in the corresponding handler file. Verify:
- Handler function exists and is importable.
- Handler has a docstring describing its behavior.
- Return type is consistent with other handlers.
- Error responses are documented.

### 3. Compare with Documentation

Read existing documentation files in `docs/`. Flag:
- **Missing**: routes documented in code but not in docs.
- **Stale**: routes in docs whose handler signatures changed.
- **Ghost**: routes in docs that no longer exist in code.
- **Incomplete**: routes documented without error scenarios or parameter descriptions.

### 4. Report

Output a concise report:

```
## API Doc Review

### ✅ Up to date
- GET /health → handle_health ✓

### ⚠️ Needs update
- POST /cards → handle_create_card: docstring missing error codes
- PUT /config: route documented but handler has new `force` parameter

### ❌ Missing from docs
- DELETE /sessions/{id}
- PATCH /settings/bulk
```

## Scope

Do NOT modify any files. Only produce the review report.
