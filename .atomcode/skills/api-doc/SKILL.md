---
name: api-doc
description: Generate and update API documentation for NOMOS Praxis API Gateway. Extracts routes, parameters, and handler signatures from api_gateway.py and api_handlers*.py.
disable-model-invocation: true
---

## Context

NOMOS Praxis API Gateway has 129+ routes registered in `src/services/api_gateway.py`, with handlers in `src/services/api_handlers.py`, `api_handlers_agent.py`, `api_handlers_cards.py`, `api_handlers_config.py`, `api_handlers_monitor.py`.

## Workflow

### 1. Scan API Routes

Read `api_gateway.py` to find all `register_route()` calls and the handler dispatch table:

```python
# Key structure in api_gateway.py:
#   Route(method, path, handler, description)
#   _register_defaults() registers all routes
#   Handlers in ApiHandlers base class
```

Read handler files to extract function signatures and docstrings.

### 2. Generate Documentation

Format as OpenAPI 3.0 (YAML or Markdown table):

```markdown
## API Reference

### `GET /health`
- **Handler**: `api_handlers.handle_health`
- **Description**: System health check
- **Response**: `{"status": str, "uptime": float}`
```

### 3. Update Existing Docs

Merge with any existing docs in `docs/` directory. Flag:
- New routes without docs
- Routes whose handler signatures changed
- Deprecated routes still documented

### Output

Write to `docs/api-reference.md` or update the existing API documentation file.
