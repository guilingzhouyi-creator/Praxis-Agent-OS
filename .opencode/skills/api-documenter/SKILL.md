---
name: api-documenter
description: Use when API routes, handlers, or API docs change — reviews documentation completeness and consistency against the registered route manifest in src/l4/api/. Flags missing, stale, and ghost routes.
---

## Overview

Automated API documentation reviewer for the Praxis codebase. Triggered when API route or handler files change, comparing registered routes against documentation to flag gaps and inconsistencies. Read-only: never modifies files.

## When to Run

Review is triggered automatically when files matching these patterns change:
- `src/l4/api/api_routes.py`
- `src/l4/api/api_gateway.py`
- `src/l4/api/api_handlers_cards.py` / `api_handlers_diff.py`
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

### Up to date
- GET /api/v2/health → handle_health OK

### Needs update
- POST /api/v2/cards → handler docstring missing error codes
- PUT /api/v2/config: route documented but handler has new `force` parameter

### Missing from docs
- DELETE /api/v2/sessions/{id}
- PATCH /api/v2/settings/bulk
```

## Scope

Do NOT modify any files. Only produce the review report.
