# ErrorLog 总线架构设计

## 1. 设计目标

将全项目分散的 ~190 个异常捕获点合流到一条统一的**错误日志总线**，对外暴露 REST API 供前端使用。

```
┌──────────────────────────────────────────────────────────────────┐
│                         前端 (Web UI)                             │
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
│  │  (合流入口)    │  │  (指纹去重)   │  │  (LogService + Event) │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
│                        │                                         │
│                        ▼                                         │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    Ring Buffer (ERROR_BUS_BUFFER)         │    │
│  │    内存环形缓冲区，按时间排序，支持快速分页查询              │    │
│  └──────────────────────────────────────────────────────────┘    │
└───────────────────────────┬──────────────────────────────────────┘
                            │
          ┌─────────────────┼──────────────────────┐
          ▼                 ▼                       ▼
┌─────────────────┐ ┌──────────────┐ ┌──────────────────────┐
│   LogService    │ │   EventBus   │ │   {config_dir}/logs/  │
│  (services/log) │ │ (kernel/event)│ │   log_*.json (持久化)  │
└─────────────────┘ └──────────────┘ └──────────────────────┘
```

---

## 2. 核心数据结构

### ErrorLogEntry — 比现有 LogEntry 更丰富

```python
@dataclass
class ErrorLogEntry:
    # ── 基础字段（继承自 LogEntry 语义） ──
    level: str                    # "ERROR" | "CRITICAL" | "WARN"
    service: str                  # 服务名, e.g. "kernel/allocator", "services/agent_loop"
    message: str                  # 人类可读错误消息
    timestamp: float              # 时间戳 (time.time())
    agent_id: str                 # 关联 agent (可选)
    task_id: str                  # 关联任务 (可选)

    # ── 新增错误专用字段 ──
    error_code: str               # 错误码, e.g. "E_INTERNAL", "E_TIMEOUT", "EFAULT"
    component: str                # 组件分层: "kernel" | "services" | "tools" | "api" | "cli"
    source: str                   # 源码位置, e.g. "kernel/allocator.py:77"
    stack_trace: str              # 堆栈追踪 (截断前 1000 字符)
    context: dict                 # 附加上下文, e.g. {"resource": "memory", "amount": 1024}
    fingerprint: str              # 去重指纹: sha256(level + error_code + source + message[:100])
    count: int                    # 同一指纹累计出现次数 (去重用)

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

### 与现有 LogEntry 的关系

```
LogEntry (services/log.py)         ErrorLogEntry (services/error_bus.py)
├── level                          ├── level (继承)
├── service                        ├── service (继承)
├── message                        ├── message (继承)
├── timestamp                      ├── timestamp (继承)
├── agent_id                       ├── agent_id (继承)
├── task_id                        ├── task_id (继承)
                                   ├── error_code ★ 新增
                                   ├── component  ★ 新增
                                   ├── source     ★ 新增
                                   ├── stack_trace ★ 新增
                                   ├── context    ★ 新增
                                   ├── fingerprint★ 新增（去重用）
                                   └── count      ★ 新增（去重累计）
```

---

## 3. 总线接口设计

### ErrorBus 类

```python
class ErrorBus:
    """统一错误日志总线 — 合流入口"""

    def __init__(self, max_entries: int = ERROR_BUS_BUFFER):
        ...

    # ── 合流入口 ──

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
        """记录一条 ERROR 级别错误 → LogService + EventBus + RingBuffer"""

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
        """从 Exception 对象提取信息并记录（自动提取 stack_trace + source）"""

    def warn(self, ...) -> dict:
        """记录一条 WARN 级别警告"""

    # ── 查询 ──

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
        """按条件查询错误日志（分页）"""

    def get_by_fingerprint(self, fingerprint: str) -> dict | None:
        """按指纹获取单条错误详情"""

    def stats(self) -> dict:
        """错误统计：按 level/error_code/component 聚合"""

    def trend(self, window_minutes: int = 60) -> list[dict]:
        """错误趋势：按时间窗口分桶统计"""

    # ── 维护 ──

    def clear(self, before: float | None = None) -> dict:
        """清空（可指定时间点之前）"""

    def export(self, path: str = "") -> dict:
        """导出错误日志到 JSON 文件"""

    # ── 去重 ──

    def _compute_fingerprint(self, level: str, error_code: str,
                              source: str, message: str) -> str:
        """sha256(level + error_code + source + message[:100]) → hex[:16]"""

    def _dedup_or_record(self, entry: ErrorLogEntry) -> ErrorLogEntry:
        """指纹命中 count+=1 不新增；未命中 append"""
```

### 辅助函数 — 全局快捷入口

```python
# 全局单例
def get_bus() -> ErrorBus: ...

# 快捷函数 — 所有 except 点无脑调用
def capture(
    message: str,
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    exc: Exception | None = None,
    **context,
) -> dict:
    """最简入口：一行替换 logger.warning / pass"""
```

---

## 4. REST API 接口（供前端使用）

所有接口以 `/api/logs/` 为前缀，遵循现有 API Gateway 的 `POST` + JSON body 风格。

| 方法 | 路径 | 说明 | 前端用途 |
|------|------|------|----------|
| `GET` | `/api/logs/errors` | 分页查询错误列表 | 错误列表页 |
| `GET` | `/api/logs/errors/:fingerprint` | 错误详情 | 错误详情页 |
| `GET` | `/api/logs/errors/stats` | 错误统计总览 | 仪表盘 |
| `GET` | `/api/logs/errors/trend` | 错误趋势（时间桶） | 趋势图 |
| `POST` | `/api/logs/errors/clear` | 清除已解决的错误 | 维护操作 |
| `GET` | `/api/logs/errors/stream` | SSE 实时错误流 | 实时通知 |
| `GET` | `/api/logs/export` | 导出错误日志 JSON | 运维导出 |
| `GET` | `/api/logs` | 通用日志查询（LogService） | 日志浏览 |
| `GET` | `/api/logs/stats` | 日志统计（LogService） | 仪表盘 |

### 请求/响应示例

**GET /api/logs/errors**

请求参数（JSON body）：
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

响应：
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

响应：
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

响应：
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

## 5. 集成层：改造所有 except 点

### 替换策略 — 一条原则

```
🔴 原来: except Exception: pass
🟢 改成: except Exception as e:
            capture("xxx failed", exc=e, component="xxx", source="xxx.py:N")

🟡 原来: except Exception as e: logger.warning("xxx: %s", e)
🟢 改成: except Exception as e:
            logger.warning("xxx: %s", e)     # 保留向下兼容
            capture("xxx failed", exc=e, ...) # 新增总线推送
```

### `src/services/error_bus.py` 中的 `capture()` 设计

```python
# 一行替代所有 except 点中的 pass / logger.warning
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
    错误捕获快捷入口。

    用法:
        try:
            ...
        except Exception as e:
            capture("memory compact failed", exc=e, component="services")

    自动提取:
      - source: 调用栈 caller 的文件:行号
      - stack_trace: exc 的 traceback
    """
    bus = get_bus()
    source = _caller_source()  # 自动推断调用位置
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

### 四阶段改造计划

| 阶段 | 范围 | 改动量 | 效果 |
|------|------|--------|------|
| **P0** | 🔴 62 个无声吞掉点 | ~62 处 | 消除静默丢失 |
| **P1** | 🟢 kernel/ 的 30 个 logger 点 | ~30 处 | 核心层接入总线 |
| **P2** | 🟢 services/ 的 45 个 logger 点 | ~45 处 | 服务层接入总线 |
| **P3** | 🟢 tools/ + api/ 其余点 | ~30 处 | 全量覆盖 |

---

## 6. EventBus 集成

ErrorBus 在 `ingest()` 时自动 `emit_event("error_log", entry.to_dict(), source=component)`。

已有 LogService 也订阅 `STATE_CHANGE` — 同样的机制：

```python
# ErrorBus 启动时注册
bus = get_event_bus()
bus.on_event("error_log", self._on_error_event)

def _on_error_event(self, signal: Signal) -> None:
    """实时推送给 SSE 订阅者"""
    with self._sse_lock:
        for queue in self._sse_clients:
            queue.put(signal.data)
```

---

## 7. 集成层接入方案（吞掉点改造成略）

### 7.1 接口总表

所有 except 点统一替换为以下两种模式之一：

| 原模式 | 替换为 | 适用范围 |
|--------|--------|----------|
| `except Exception: pass` | `except Exception as e: capture("...", exc=e, component="...")` | 所有 silent swallow |
| `except Exception as e: logger.warning("...", e)` | `except Exception as e: logger.warning("...", e); capture("...", exc=e, component="...")` | 已有日志但需合流 |
| `except Exception as e: return {"error": str(e)}` | `except Exception as e: capture("...", exc=e, ...); return {"error": str(e)}` | API handler 返回前记录 |
| `except ImportError:` | `except ImportError as e: capture("import failed", exc=e, error_code="E_MISSING_DEP")` | ImportError 专用 |

### 7.2 P0 — 消除 62 个无声吞掉点（按文件分组）

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

### 7.3 P1+P2+P3 — 提升已有日志点到总线（示例片段）

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

## 8. 新增/修改文件清单 (整理)

| 文件 | 状态 | 说明 |
|------|------|------|
| `docs/design/praxis-error-bus-design.md` | ✅ 新建 | 本设计文档 |
| `src/services/error_bus.py` | ✅ 新建 | ErrorBus 核心 + capture + API handlers |
| `src/kernel/params.py` | ✅ 修改 | 新增 3 个 ERROR_BUS_* 常量 |
| `src/services/api_gateway.py` | ✅ 修改 | 注册 LOG_ROUTES 到 API Gateway |
| `src/services/api_handlers.py` | 🔜 可选 | 可将 handler 混入 ApiHandlers 类（已有 LOG_ROUTES 独立模式） |
| 全项目 ~190 个 except 点 | 🔜 待改造 | 按 P0→P1→P2→P3 阶段逐步替换 |

## 8. 前端对接契约

前端只需对接 REST API：

```typescript
// 前端类型定义（供参考）
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

## 9. 与现有系统的关系

```
PraxisError (kernel/errors.py)          ErrorBus (services/error_bus.py)
├── 错误码定义                             ├── 错误记录引擎
├── 返回结构化 dict                        ├── 总线合流 + 去重
├── i18n 翻译                             ├── 查询 + 统计
└── 供工具 handler 使用                    └── REST API 暴露

LogService (services/log.py)              EventBus (kernel/event.py)
├── 通用日志                               ├── 实时事件分发
├── 磁盘持久化 + 轮转                       └── SSE 推送
├── 通用查询
└── 被 ErrorBus 调用（写日志目的地）
```
