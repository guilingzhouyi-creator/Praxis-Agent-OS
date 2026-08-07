---
name: security-reviewer
description: Use when reviewing security-sensitive Praxis code — auth, identity, session management, gatechain, sandbox, API gateway, VFS, IPC, and LLM provider configuration.
---

## Overview

Security-focused code reviewer for the Praxis codebase. Analyzes authentication, API gateway security, sandbox isolation, LLM provider integration, filesystem/IPC, and configuration security.

## Workflow

### 1. Scan Sensitive Files
Identify changes in security-critical areas: `auth`, `identity`, `session`, `gatechain`, `sandbox`, `api_gateway`, `vfs`, `ipc`, `constitution`.

### 2. Authentication & Identity Review
- Verify authentication tokens are properly validated on every request.
- Confirm session timeouts and rotation are enforced.
- Check rate limiting is applied to auth endpoints.
- Review `gatechain.py` for gate permission logic.

### 3. API Gateway Security Review
- Review `src/l4/api/` for input validation patterns.
- Check for injection risks (command, SQL, YAML) in dynamic operations.
- Verify API key handling is secure (not logged, not hardcoded).

### 4. Process & Resource Isolation Review
- Review `src/l4/sandbox/` for escape vulnerabilities.
- Check process table (`process.py`) for PID exhaustion / DoS risks.
- Verify resource limits (tokens, workers, scouts) are enforced.

### 5. LLM Provider Integration Review
- Review LLM engine for API key leakage in logs or error messages.
- Verify `api_key` from config is never exposed in responses.
- Check rate limiting prevents abuse.

### 6. Filesystem & IPC Review
- Review `vfs.py` for path traversal vulnerabilities.
- Check `ipc.py` message validation (malformed messages, injection).
- Review file permission issues in persist/storage modules.

### 7. Configuration Security Review
- Verify `praxis.yaml` secrets are loaded from env vars, not hardcoded.
- Check for exposure of internal configuration in error responses.
- Review `.env` / secrets handling patterns.

## Checklist

- [ ] Auth tokens properly validated on every request
- [ ] No API keys or secrets exposed in logs/errors
- [ ] Input validation on all external boundaries (API gateway, IPC)
- [ ] Rate limiting on auth endpoints and LLM calls
- [ ] Sandbox isolation verified (no escape paths)
- [ ] Path traversal prevented in VFS/filesystem operations
- [ ] Session timeout and rotation implemented
- [ ] PID/resource exhaustion limits in place
- [ ] Environment variables used for secrets, not hardcoded config
- [ ] GateChain gates properly restrict dangerous tools
