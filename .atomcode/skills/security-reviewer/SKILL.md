---
name: security-reviewer
description: Security-focused code review for NOMOS Praxis. Analyzes auth, identity, session management, and API gateway code.
allowed-tools: Read, Grep, Glob
---

## Security Review Focus Areas

### Authentication & Identity
- Review `auth.py`, `identity.py`, `user_session.py` for security patterns
- Check that authentication tokens are properly validated
- Ensure session timeouts and rotation are enforced
- Verify rate limiting is applied to auth endpoints

### API Gateway Security
- Review `api_gateway.py` for input validation patterns
- Check for SQL injection / command injection risks in dynamic operations
- Verify API key handling is secure (not logged, not hardcoded)

### Process & Resource Isolation
- Review `sandbox.py` for escape vulnerabilities
- Check process table (`process.py`) for PID exhaustion / DoS risks
- Verify resource limits (tokens, workers, scouts) are enforced

### LLM Provider Integration
- Review `llm.py` for API key leakage in logs or error messages
- Check that `api_key` from config is never exposed in responses
- Verify rate limiting prevents abuse

### Filesystem & IPC
- Review `vfs.py` for path traversal vulnerabilities
- Check `ipc.py` message validation (malformed messages, injection)
- Review `fs.py` for file permission issues

### Configuration Security
- Verify `praxis.yaml` secrets are loaded from env vars, not hardcoded
- Check for exposure of internal configuration in error responses
- Review `.env` / secrets handling patterns

### Checklist
- [ ] Auth tokens properly validated on every request
- [ ] No API keys or secrets exposed in logs/errors
- [ ] Input validation on all external boundaries (API gateway, IPC)
- [ ] Rate limiting on auth endpoints and LLM calls
- [ ] Sandbox isolation verified (no escape paths)
- [ ] Path traversal prevented in VFS/filesystem operations
- [ ] Session timeout and rotation implemented
- [ ] PID/resource exhaustion limits in place
- [ ] Environment variables used for secrets, not hardcoded config
