# ErrorLog Bus Architecture Design

## 1. Design Goals

Merge ~190 scattered exception capture points across the project into a unified **error log bus**, exposing a REST API for the frontend.

```
┌──────────────────────────────────────────────────────────────────┐
│                       Frontend (Web UI)                           │
│        ┌───────────┐  ┌──────────┐  ┌───────────┐              │
│        │ ErrorList  │  │ ErrorDetail│ │ ErrorStats│              │
│        └─────┬─────┘  └────┬─────┘  └─────┬─────┘              │
└──────────────┼─────────────┼───────────────┼────────────────────┘
               │  HTTP REST  │               │
               ▼             ▼               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    API Gateway (:8080)                            │
│    /api/logs/errors    /api/logs/errors/:id   /api/logs/stats    │
│    /api/logs/errors/stream (SSE)  /api/logs/export               │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│                     ErrorBus (services/error_bus.py)              │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │  ingest()     │→│  dedup()      │→│  emit_to_bus()        │  │
│  │  (Ingress)    │  │  (Fingerprint │  │  (LogService + Event) │  │
│  │               │  │   dedup)     │  │                       │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
│                        │                                         │
│                        ▼                                         │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │              Ring Buffer (ERROR_BUS_BUFFER)               │    │
│  │    In-memory ring buffer, sorted by time, supports       │    │
│  │    fast paginated queries                                │    │
│  └──────────────────────────────────────────────────────────┘    │
└───────────────────────────┬──────────────────────────────────────┘
                            │
          ┌─────────────────┼──────────────────────┐
          ▼                 ▼                       ▼
┌─────────────────┐ ┌──────────────┐ ┌──────────────────────┐
│   LogService    │ │   EventBus   │ │   {config_dir}/logs/  │
│  (services/log) │ │ (kernel/event)│ │   log_*.json (Persist)│
└─────────────────┘ └──────────────┘ └──────────────────────┘
```

---

## 2. Core Data Structure

### ErrorLogEntry — Richer than the existing LogEntry

```python
@dataclass
class ErrorLogEntry:
    # ── Base Fields (inherited from LogEntry semantics) ──
    level: str                    # "ERROR" | "CRITICAL" | "WARN"
    service: str                  # Service name, e.g. "kernel/allocator", "services/agent_loop"
    message: str                  # Human-readable error message
    timestamp: float              # Timestamp (time.time())
    agent_id: str                 # Associated agent (optional)
    task_id: str                  # Associated task (optional)

    # ── New error-specific fields ──
    error_code: str               # Error code, e.g. "E_INTERNAL", "E_TIMEOUT", "EFAULT"
    component: str                # Component layer: "kernel" | "services" | "tools" | "api" | "cli"
    source: str                   # Source location, e.g. "kernel/allocator.py:77"
    stack_trace: str              # Stack trace (truncated to first 1000 chars)
    context: dict                 # Additional context, e.g. {"resource": "memory", "amount": 1024}
    fingerprint: str              # Dedup fingerprint: sha256(level + error_code + source + message[:100])
    count: int                    # Cumulative occurrence count for the same fingerprint (for dedup)

    def to_dict(self) -> dict:
        return {
            "id": self.fingerprint[:12],
            "level": self.level,
            "error_code": self.error_code,
            "component": self.component,
            "service": self.service,
            "message": self.message[:500],
            "source": self.source,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "stack_trace": self.stack_trace[:1000] if self.stack_trace else "",
            "context": self.context,
            "count": self.count,
        }
```

### Relationship with Existing LogEntry

```
LogEntry (services/log.py)         ErrorLogEntry (services/error_bus.py)
├── level                          ├── level (inherited)
├── service                        ├── service (inherited)
├── message                        ├── message (inherited)
├── timestamp                      ├── timestamp (inherited)
├── agent_id                       ├── agent_id (inherited)
├── task_id                        ├── task_id (inherited)
                                   ├── error_code ★ New
                                   ├── component  ★ New
                                   ├── source     ★ New
                                   ├── stack_trace ★ New
                                   ├── context    ★ New
                                   ├── fingerprint★ New (for dedup)
                                   └── count      ★ New (dedup accum)
```

---

## 3. Bus Interface Design

### ErrorBus Class

```python
class ErrorBus:
    """Unified error log bus — ingress point"""

    def __init__(self, max_entries: int = ERROR_BUS_BUFFER):
        ...

    # ── Ingress ──

    def error(
        self,
        message: str,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Record an ERROR level error → LogService + EventBus + RingBuffer"""

    def exception(
        self,
        exc: Exception,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Extract info from an Exception object and record (auto-extract stack_trace + source)"""

    def warn(self, ...) -> dict:
        """Record a WARN level warning"""

    # ── Query ──

    def query(
        self,
        level: str | None = None,
        error_code: str | None = None,
        component: str | None = None,
        service: str | None = None,
        agent_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Query error logs by criteria (paginated)"""

    def get_by_fingerprint(self, fingerprint: str) -> dict | None:
        """Get a single error detail by fingerprint"""

    def stats(self) -> dict:
        """Error stats: aggregated by level/error_code/component"""

    def trend(self, window_minutes: int = 60) -> list[dict]:
        """Error trend: bucketed by time window"""

    # ── Maintenance ──

    def clear(self, before: float | None = None) -> dict:
        """Clear (can specify a time before a given point)"""

    def export(self, path: str = "") -> dict:
        """Export error logs to JSON file"""

    # ── Dedup ──

    def _compute_fingerprint(self, level: str, error_code: str,
                              source: str, message: str) -> str:
        """sha256(level + error_code + source + message[:100]) → hex[:16]"""

    def _dedup_or_record(self, entry: ErrorLogEntry) -> ErrorLogEntry:
        """Fingerprint hit → count+=1, no new entry; miss → append"""
```

### Helper Functions — Global Quick Entry

```python
# Global singleton
def get_bus() -> ErrorBus: ...

# Quick function — blindly call at all except points
def capture(
    message: str,
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    exc: Exception | None = None,
    **context,
) -> dict:
    """Simplest entry: one-line replacement for logger.warning / pass"""
```

---

## 4. REST API Interface (for Frontend Use)

All endpoints are prefixed with `/api/logs/` and follow the existing API Gateway's `POST` + JSON body style.

| Method | Path | Description | Frontend Use |
|--------|------|-------------|--------------|
| `GET` | `/api/logs/errors` | Paginated query of error list | Error list page |
| `GET` | `/api/logs/errors/:fingerprint` | Error details | Error detail page |
| `GET` | `/api/logs/errors/stats` | Error stats overview | Dashboard |
| `GET` | `/api/logs/errors/trend` | Error trend (time buckets) | Trend chart |
| `POST` | `/api/logs/errors/clear` | Clear resolved errors | Maintenance operation |
| `GET` | `/api/logs/errors/stream` | SSE real-time error stream | Real-time notifications |
| `GET` | `/api/logs/export` | Export error log JSON | Ops export |
| `GET` | `/api/logs` | General log query (LogService) | Log browsing |
| `GET` | `/api/logs/stats` | Log stats (LogService) | Dashboard |

### Request/Response Example

**GET /api/logs/errors**

Request params (JSON body):
```json
{
    "level": "ERROR",
    "error_code": "E_INTERNAL",
    "component": "kernel",
    "service": "kernel/allocator",
    "agent_id": "agent-cell-1",
    "since": 1721800000.0,
    "until": 1721886400.0,
    "offset": 0,
    "limit": 50
}
```

Response:
```json
{
    "success": true,
    "total": 128,
    "offset": 0,
    "limit": 50,
    "entries": [
        {
            "id": "a1b2c3d4e5f6",
            "level": "ERROR",
            "error_code": "E_INTERNAL",
            "component": "kernel",
            "service": "kernel/allocator",
            "message": "OOM: killed agent-cell-2 (priority=5)",
            "source": "kernel/allocator.py:206",
            "timestamp": 1721886000.123,
            "datetime": "2026-07-25T10:00:00+00:00",
            "agent_id": "agent-cell-2",
            "stack_trace": "Traceback ...",
            "context": {"resource": "memory", "priority": 5},
            "count": 3
        }
    ]
}
```

**GET /api/logs/errors/stats**

Response:
```json
{
    "success": true,
    "total": 128,
    "by_level": {"ERROR": 100, "CRITICAL": 20, "WARN": 8},
    "by_error_code": {
        "E_INTERNAL": 45, "E_TIMEOUT": 30, "EFAULT": 20,
        "E_RESOURCE_EXHAUSTED": 15, "E_HANDLER_ERROR": 10, "E_PERMISSION_DENIED": 8
    },
    "by_component": {
        "kernel": 60, "services": 55, "tools": 10, "api": 3
    },
    "top_sources": [
        {"source": "kernel/allocator.py:206", "count": 15},
        {"source": "services/agent_loop.py:636", "count": 12},
        ...
    ],
    "disk_files": 8,
    "log_dir": "/home/user/.praxis/logs"
}
```

**GET /api/logs/errors/trend?window=60**

Response:
```json
{
    "success": true,
    "window_minutes": 60,
    "buckets": [
        {"bucket": "2026-07-25T09:00:00", "count": 12},
        {"bucket": "2026-07-25T10:00:00", "count": 8},
        {"bucket": "2026-07-25T11:00:00", "count": 25}
    ]
}
```

**GET /api/logs/errors/stream** (SSE)

```
data: {"type": "error", "entry": {"id": "a1b2...", "level": "ERROR", ...}}

data: {"type": "error", "entry": {...}}
```

---

## 5. Integration Layer: Migrate All except Points

### Replacement Strategy — One Principle

```
🔴 Before: except Exception: pass
🟢 After:  except Exception as e:
               capture("xxx failed", exc=e, component="xxx", source="xxx.py:N")

🟡 Before: except Exception as e: logger.warning("xxx: %s", e)
🟢 After:  except Exception as e:
               logger.warning("xxx: %s", e)     # Keep backward compat
               capture("xxx failed", exc=e, ...) # New bus push
```

### `capture()` Design in `src/services/error_bus.py`

```python
# One-line replacement for pass / logger.warning in all except points
def capture(
    message: str,
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    exc: Exception | None = None,
    agent_id: str = "",
    task_id: str = "",
    context: dict | None = None,
) -> dict:
    """
    Error capture quick entry.

    Usage:
        try:
            ...
        except Exception as e:
            capture("memory compact failed", exc=e, component="services")

    Auto-extracts:
      - source: caller's file:line
      - stack_trace: exc's traceback
    """
    bus = get_bus()
    source = _caller_source()  # Auto-infer call location
    stack_trace = _format_exc(exc) if exc else ""
    return bus.error(
        message=message,
        error_code=error_code,
        component=component,
        source=source,
        stack_trace=stack_trace,
        agent_id=agent_id,
        task_id=task_id,
        context=context or {},
    )
```

### Four-Phase Migration Plan

| Phase | Scope | Changes | Effect |
|-------|-------|---------|--------|
| **P0** | 🔴 62 silent swallow points | ~62 places | Eliminate silent loss |
| **P1** | 🟢 30 logger points in kernel/ | ~30 places | Kernel layer connects to bus |
| **P2** | 🟢 45 logger points in services/ | ~45 places | Service layer connects to bus |
| **P3** | 🟢 Remaining points in tools/ + api/ | ~30 places | Full coverage |

---

## 6. EventBus Integration

ErrorBus automatically emits `emit_event("error_log", entry.to_dict(), source=component)` on `ingest()`.

The existing LogService also subscribes to `STATE_CHANGE` — same mechanism:

```python
# ErrorBus registers on startup
bus = get_event_bus()
bus.on_event("error_log", self._on_error_event)

def _on_error_event(self, signal: Signal) -> None:
    """Push to SSE subscribers in real time"""
    with self._sse_lock:
        for queue in self._sse_clients:
            queue.put(signal.data)
```

---

## 7. Integration Layer Migration Plan (Swallow Point Retrofit Strategy)

### 7.1 Interface Summary Table

All except points are uniformly replaced by one of the following patterns:

| Original Pattern | Replace With | Scope |
|------------------|-------------|-------|
| `except Exception: pass` | `except Exception as e: capture("...", exc=e, component="...")` | All silent swallow |
| `except Exception as e: logger.warning("...", e)` | `except Exception as e: logger.warning("...", e); capture("...", exc=e, component="...")` | Existing log but needs bus integration |
| `except Exception as e: return {"error": str(e)}` | `except Exception as e: capture("...", exc=e, ...); return {"error": str(e)}` | Record before returning from API handler |
| `except ImportError:` | `except ImportError as e: capture("import failed", exc=e, error_code="E_MISSING_DEP")` | ImportError-specific |

### 7.2 P0 — Eliminate 62 Silent Swallow Points (Grouped by File)

```
src/main.py
  L36  except Exception: pass           → capture("shutdown handler register failed", component="main")
  L58  except Exception: pass           → capture("main loop error", component="main")

src/cli.py
  L189 except Exception: pass           → capture("cli status display failed", component="cli")

src/kernel/net.py
  L173 except Exception: continue       → capture("udp discovery handler error", component="kernel")
  L163 except Exception: continue       → capture("udp discovery error", component="kernel")

src/kernel/persist.py
  L162 except Exception: continue       → capture("event replay json parse failed", component="kernel")
  L310 except Exception: ok = False     → capture("persist cleanup failed", component="kernel")

src/kernel/platform.py
  L182 except Exception: pass           → capture("log file read failed", component="kernel")
  L188 except Exception: return []      → capture("file read failed", component="kernel")

src/kernel/skill.py
  L162 except Exception: return False   → capture("skill file read failed", component="kernel")
  L171 except Exception: return False   → capture("skill yaml parse failed", component="kernel")

src/services/agent_loop.py
  L366 except Exception: pass           → capture("state file cleanup failed", component="services")
  L636 except Exception: pass           → capture("memory compact failed", component="services")
  L705 except Exception: pass           → capture("stub compact failed", component="services")

src/services/agent_terminal.py
  L320 except Exception: ...skip        → capture("memory store failed", component="services")
  L337 except Exception: ...skip        → capture("cross review failed", component="services")
  L439 except Exception: pass           → capture("direct session archive failed", component="services")

src/services/card_gate.py
  L139 except Exception: pass           → capture("approval set failed", component="services")

src/services/card_registry.py
  L120 except Exception: pass           → capture("gate auto approve failed", component="services")
  L200 except Exception: fallback       → capture("gate evaluate failed", component="services")
  L293 except Exception: fallback       → capture("llm plan parse failed", component="services")

src/services/central_memory.py
  L49  except Exception: pass           → capture("quality score failed", component="services")
  L99  except Exception: pass           → capture("ring4 recall failed", component="services")
  L138 except Exception: pass           → capture("memory stats failed", component="services")
  L145 except Exception: pass           → capture("r4 stats failed", component="services")

src/services/central_security.py
  L137 except Exception: fallback       → capture("rate limit check failed", component="services")

src/services/config_handlers.py
  L236 except Exception: dtype=fallback → capture("device type parse failed", component="services")

src/services/config_loader.py
  L192 except Exception: fallback       → capture("provider list failed", component="services")

src/services/convergence.py
  L121 except Exception: fallback       → capture("llm converge failed", component="services")

src/services/dialogue_session.py
  L240 except Exception: return None    → capture("session restore failed", component="services")

src/services/htn_planner.py
  L113 except Exception: fallback       → capture("htn params failed", component="services")

src/services/issue.py
  L285 except Exception: pass           → capture("draft delete failed", component="services")

src/services/l2_shell.py
  L125 except Exception: pass           → capture("agent autocomplete failed", component="services")
  L556 except Exception: pass           → capture("close direct session failed", component="services")

src/services/llm.py
  L75  except Exception: return cls()   → capture("provider create failed", component="services")
  L342 except Exception: pass           → capture("retry memory compact failed", component="services")
  L359 except Exception: return {...}   → capture("llm json decode failed", component="services")
  L416 except Exception: config=default → capture("llm config load failed", component="services")

src/services/llm_providers.py
  L45,108,179,215: except Exception: return default → capture("settings get failed", component="services")

src/services/lsp.py
  L54  except Exception: return False   → capture("pyright check failed", component="services")
  L108 except Exception: continue       → capture("lsp file read failed", component="services")
  L148 except Exception: pass           → capture("pyright parse failed", component="services")

src/services/mcp_bridge.py
  L102 except Exception: return False   → capture("mcp ping failed", component="services")

src/services/memory.py
  L470 except Exception: return []      → capture("memory db query failed", component="services")

src/services/memory_init.py
  L76  except Exception: return None    → capture("memory load failed", component="services")

src/services/observability_bus.py
  L107,113,119,125: except Exception: fallback → capture("obs subsystem failed", component="services")

src/services/pending_queue.py
  L138 except Exception: pass           → capture("pending approval set failed", component="services")

src/services/process.py
  L118 except Exception: break          → capture("process reader error", component="services")

src/services/selector.py
  L83  except Exception: return fallback → capture("cell service unavailable", component="services")
  L198 except Exception: continue       → capture("agent lookup failed", component="services")
  L211 except Exception: pass           → capture("role lookup failed", component="services")

src/services/shell.py
  L118 except Exception: fallback       → capture("tool list failed", component="services")

src/services/shell_completer.py
  L48  except Exception: return fallback → capture("registry load failed", component="services")
  L72  except Exception: return None    → capture("complete failed", component="services")

src/services/shell_session.py
  L129 except Exception: break          → capture("shell session read error", component="services")

src/services/verifier.py
  L49  except Exception: fallback       → capture("llm verify failed", component="services")
  L91  except Exception: pass           → capture("consistency check failed", component="services")

src/services/_term_lifecycle.py
  L44  except Exception: pass           → capture("keepalive check failed", component="services")

src/services/fs.py
  L62  except OSError: continue         → capture("file stat failed", component="services")

src/tools/advanced/tools_notify.py
  L22  except Exception: fallback       → capture("notify json parse failed", component="tools")

src/tools/base/tools_context.py
  L48  except Exception: fallback       → capture("context json parse failed", component="tools")

src/tools/base/tools_data.py
  L88  except Exception: return error   → capture("schema json parse failed", component="tools")
  L128 except Exception: fallback       → capture("mapping json parse failed", component="tools")

src/tools/special/tools_archive.py
  L110 except Exception: return 0       → capture("archive db count failed", component="tools")
```

### 7.3 P1+P2+P3 — Upgrade Existing Log Points to the Bus (Sample Snippet)

```diff
// kernel/event.py
  except Exception as e:
      logger.warning("event handler: %s", e)
+     capture("event handler failed", exc=e, component="kernel",
+             source="kernel/event.py:102")

// kernel/gatechain.py
  except Exception as e:
      logger.warning("kernel/gatechain: %s", e)
+     capture("gate chain evaluate failed", exc=e, component="kernel",
+             source="kernel/gatechain.py:155")

// services/agent_loop.py
  except Exception as e:
      logger.warning("parallel tool %s: %s", ...)
+     capture("parallel tool failed", exc=e, component="services",
+             source="services/agent_loop.py:801")
```

---

## 8. New/Modified File Summary

| File | Status | Description |
|------|--------|-------------|
| `docs/design/praxis-error-bus-design.md` | ✅ New | This design document |
| `src/services/error_bus.py` | ✅ New | ErrorBus core + capture + API handlers |
| `src/kernel/params.py` | ✅ Modified | Add 3 ERROR_BUS_* constants |
| `src/services/api_gateway.py` | ✅ Modified | Register LOG_ROUTES with API Gateway |
| `src/services/api_handlers.py` | 🔜 Optional | Can mix handlers into ApiHandlers class (already has LOG_ROUTES standalone mode) |
| ~190 except points across the project | 🔜 Pending | Gradually replace by phase P0→P1→P2→P3 |

## 8. Frontend Integration Contract

Frontend only needs to integrate with the REST API:

```typescript
// Frontend type definition (for reference)
interface ErrorLogEntry {
    id: string;           // fingerprint[:12]
    level: 'ERROR' | 'CRITICAL' | 'WARN';
    error_code: string;
    component: string;
    service: string;
    message: string;
    source: string;
    timestamp: number;
    datetime: string;     // ISO 8601
    agent_id: string;
    task_id: string;
    stack_trace: string;
    context: Record<string, unknown>;
    count: number;
}

interface ErrorLogStats {
    total: number;
    by_level: Record<string, number>;
    by_error_code: Record<string, number>;
    by_component: Record<string, number>;
    top_sources: Array<{source: string; count: number}>;
    disk_files: number;
}

interface ErrorTrendBucket {
    bucket: string;       // ISO 8601
    count: number;
}
```

---

## 9. Relationship with Existing Systems

```
PraxisError (kernel/errors.py)          ErrorBus (services/error_bus.py)
├── Error code definitions               ├── Error recording engine
├── Returns structured dict              ├── Bus merging + dedup
├── i18n translation                     ├── Query + stats
└── For tool handler use                 └── REST API exposure

LogService (services/log.py)              EventBus (kernel/event.py)
├── General logging                       ├── Real-time event distribution
├── Disk persistence + rotation           └── SSE push
├── General query
└── Called by ErrorBus (log write destination)
```
