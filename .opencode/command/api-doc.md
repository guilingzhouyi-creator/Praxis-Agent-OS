---
description: Generate or update API documentation for the Praxis API Gateway. Use /api-doc when adding API routes/handlers or updating the API reference.
---

Generate and update API documentation for the Praxis API Gateway, focusing on `$ARGUMENTS` (omit to cover the whole gateway).

## Workflow

### 1. Scan API Routes

Read `src/l4/api/api_routes.py` and `src/l4/api/api_gateway.py` to find all registered routes (all under `/api/v2/`):

```python
# Key structures:
#   ("GET", "/api/v2/health", ".health", "Kernel health")  — route tuples in api_routes.py
#   Handler functions referenced by short names like ".health"
```

### 2. Read Handler Signatures

Read handler files from `src/l4/api/api_handlers_cards.py`, `src/l4/api/api_handlers_diff.py`, and related modules to extract:
- Function signatures (parameters, return types).
- Docstrings describing behavior.
- Error response patterns.

### 3. Validate the Manifest

The endpoint manifest (`src/l4/api/api_endpoints.py`) is the single source of truth for route classification. Validate before documenting:
- Run `python -m l4.api.api_endpoints` — it rejects kebab-case violations and placeholder mismatches.
- New endpoints must be registered via `register_endpoint()` / `register_domain()` / `register_group()` — never hand-edit `API_ROUTES`.
- Breaking path changes require a new version segment (`/api/v3/`) plus a manifest entry.

### 4. Generate Documentation

Format as OpenAPI 3.0 (YAML or Markdown table):

```markdown
## API Reference

### `GET /api/v2/health`
- **Handler**: `handle_health`
- **Description**: System health check
- **Response**: `{"status": str, "uptime": float}`
```

### 5. Merge with Existing Docs

Read existing docs in `docs/`. Flag:
- New routes without documentation.
- Routes whose handler signatures changed.
- Deprecated routes still documented.

## Output

Write to `docs/api-reference.md` or update the existing API documentation file. Report a summary of what was added, updated, or removed.
