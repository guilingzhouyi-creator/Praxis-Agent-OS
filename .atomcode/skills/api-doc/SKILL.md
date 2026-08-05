---
name: api-doc
description: Generate and update API documentation for NOMOS Praxis API Gateway. Extracts routes, parameters, and handler signatures from api_gateway.py and api_handlers*.py.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write
---

## Overview

Generates and updates OpenAPI documentation for the Praxis API Gateway. Reads routes from `src/l4/api/api_gateway.py` and handler signatures from `src/l4/api/api_handlers*.py`, then produces or merges API documentation.

## When to Use

Invoke via `/api-doc` when:
- Adding new API routes or handlers.
- Modifying existing route parameters or responses.
- Updating the API reference documentation.

## Workflow

### 1. Scan API Routes

Read `src/l4/api/api_routes.py` and `src/l4/api/api_gateway.py` to find all registered routes:

```python
# Key structures:
#   Route(method, path, handler, description)
#   _register_defaults() registers all routes
#   Handlers in api_handlers_*.py files
```

### 2. Read Handler Signatures

Read handler files from `src/l4/api/` and `src/l4/api_handlers/` to extract:
- Function signatures (parameters, return types).
- Docstrings describing behavior.
- Error response patterns.

### 3. Generate Documentation

Format as OpenAPI 3.0 (YAML or Markdown table):

```markdown
## API Reference

### `GET /health`
- **Handler**: `handle_health`
- **Description**: System health check
- **Response**: `{"status": str, "uptime": float}`
```

### 4. Merge with Existing Docs

Read existing docs in `docs/` directory. Flag:
- New routes without documentation.
- Routes whose handler signatures changed.
- Deprecated routes still documented.

## Output

Write to `docs/api-reference.md` or update the existing API documentation file. Report a summary of what was added, updated, or removed.