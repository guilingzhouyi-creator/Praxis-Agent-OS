# L4 API 网关审查报告

> **审查日期**: 2026-07-30  
> **审查范围**: `src/l4/api/`(6文件) + `src/l4/api_handlers/`(11文件)  
> **审查方法**: 全链路数据流追踪 + 路由表分析

---

## 1. 架构总览

### 文件结构

```
api/                        api_handlers/
├── __init__.py             ├── __init__.py         ← ApiHandlers mixin (107方法/836行)
├── api_gateway.py          ├── api_handlers_agent.py
├── api_middleware.py       ├── api_handlers_cluster.py
├── api_routes.py           ├── api_handlers_commands.py
├── api_handlers_cards.py   ├── api_handlers_config.py
└── api_handlers_diff.py    ├── api_handlers_constitution.py
                            ├── api_handlers_discussion.py
                            ├── api_handlers_monitor.py
                            ├── api_handlers_providers.py
                            ├── api_handlers_records.py
                            └── api_handlers_stats.py
```

### 路由表规模

`api_routes.py` 定义 **227 条路由**，覆盖 30+ 功能域：

| 功能域 | 路由数 | 代表路径 |
|--------|:------:|---------|
| Core system | 8 | `/api/health`, `/api/processes` |
| Cards | 10 | `/api/card`, `/api/cards` |
| Approvals | 7 | `/api/approvals` |
| Cell/Cluster | 6 | `/api/cell/`, `/api/cluster/` |
| Agents | 9 | `/api/agents`, `/api/agent/` |
| Security/Trust | 4 | `/api/security/`, `/api/trust/` |
| Memory | 3 | `/api/memory/` |
| Shell | 3 | `/api/shell/` |
| MCP | 3 | `/api/mcp/` |
| Plugins | 5 | `/api/plugins/` |
| Constitution | 5 | `/api/v2/constitution/` |
| Discussion | 8 | `/api/v2/discussion/` |
| Providers | 8 | `/api/v2/providers/` |
| Stats/Records | 7 | `/api/v2/stats/`, `/api/v2/records/` |
| File Editor | 10 | `/api/fs/` |
| Search/LSP | 7 | `/api/search/`, `/api/lsp/` |
| Session | 6 | `/api/session/` |
| Error Bus | 6 | `/api/logs/errors/` |
| Monitor | 6 | `/api/monitor/` |
| **其它** | **~116** | cron/credentials/buffer/export 等 |

---

## 2. 请求处理链路

### 完整数据流

```
HTTP Request
    │
    ▼
_Handler.do_GET/POST/DELETE/OPTIONS    (api_gateway.py:296-310)
    │
    ▼
_check_auth()                           L183-187
    │  调用 _auth_ok()                   L174-181
    │    └── Authorization: Bearer <token> → HMAC compare_digest
    │    └── 无 auth_token 时跳过（允许匿名）
    │
    ▼  (SSE 特殊路径)
_do_sse() ←── path == "/api/events"     L261-294
    │   SSE 订阅 + 队列循环 + 连接断开时取消订阅
    │
    ▼  (普通请求路径)
_handle_via_middleware(method)           L230-259
    │
    ├── 1. _read_body()                 L196-206  (POST/DELETE only)
    │       JSON解析, 大小限制, 拒绝chunked
    │
    ├── 2. _build_request() → Request   L211-228
    │
    ├── 3. _match_route() → handler     L126-142
    │       支持后缀匹配 (GET /api/card/{id})
    │
    ├── 4. route_handler()               L248-256
    │       包装 handler, 注入 _id, _user_id, query params
    │
    ├── 5. MiddlewareChain.handle()      middleware.py:118-143
    │        洋葱模型:
    │          Request → LocaleMiddleware(request)
    │                  → BodyParserMiddleware(request)
    │                  → RequestLogMiddleware(request)
    │                  → TimeoutMiddleware(request)
    │                  → route_handler(request) → dict
    │                  ← RequestLogMiddleware(response)
    │                  ← CORSMiddleware(response)
    │
    └── 6. _json(resp.data, resp.status) L189-194
           JSON序列化 + CORS headers
```

### SSE 事件流

```
/api/events (GET, 长连接)
    │
    ▼
_do_sse()
    ├── subscribe() → queue           L270-272
    ├── 循环:
    │     queue.get(timeout=30s)
    │       → event → "data: {json}\n\n" → wfile.write
    │       → 超时 → ": keepalive\n\n" (心跳)
    ├── 断开 (BrokenPipeError/ConnectionResetError)
    └── finally: unsubscribe()
```

---

## 3. 中间件链分析

### 洋葱模型

```
Request → [Locale → BodyParser → RequestLog → Timeout]
                                           │
                                    handler(req) → dict
                                           │
Response ← [CORS ← RequestLog] ←←←←←←←←←←←
```

### 中间件清单

| 中间件 | process() | process_response() | 行数 |
|--------|-----------|-------------------|:----:|
| **LocaleMiddleware** | Accept-Language → 设置i18n locale | — | 26 |
| **CORSMiddleware** | — | 添加 CORS headers | 15 |
| **BodyParserMiddleware** | 校验 Content-Type + JSON 解析 | — | 16 |
| **RequestLogMiddleware** | 记录 request 日志（debug级） | 记录 response 日志（info级） | 19 |
| **TimeoutMiddleware** | 设置 signal alarm（POSIX only） | — | 13 |

### Handler 类型

| 类型 | 注册方式 | 示例 | 数量 |
|------|---------|------|:----:|
| **ApiHandlers mixin** | `.method_name` | `.list_cards` | ~70 |
| **services.xxx** | `services.xxx.yyy` | `services.api_handlers_diff.diff_structured` | ~150 |
| **l3.xxx** | `l3.xxx.yyy` | `l3.prompt_engine.handle_prompt_build` | ~7 |

---

## 4. 认证机制

### 当前实现

```python
def _auth_ok(self) -> bool:
    import hmac
    if not self.gateway.auth_token:
        return True  # ← 无 token = 允许所有匿名访问
    received = self.headers.get("Authorization", "").replace("Bearer ", "")
    if len(received) != len(self.gateway.auth_token):
        return False
    return hmac.compare_digest(received, self.gateway.auth_token)
```

### 评价

| 维度 | 状态 | 说明 |
|------|------|------|
| 算法 | ✅ | 使用 `hmac.compare_digest()`（恒定时间比较） |
| 匿名降级 | ✅ 可接受 | 无 `auth_token` 时允许匿名（开发环境适用） |
| Token 来源 | ✅ | 仅读 `Authorization: Bearer` header |
| 没有 JWT | ℹ️ | 使用简单 bearer token，适用内部 API |
| 没有角色/权限 | ℹ️ | 所有认证用户拥有完全权限 |

---

## 5. SSE 实现分析

| 维度 | 状态 | 说明 |
|------|------|------|
| 协议 | ✅ | 标准 SSE：`data: {json}` + `keepalive` |
| 订阅 | ✅ | 通过 `l4.sse.sse_bridge.subscribe()` |
| 超时 | ✅ | `queue.get(timeout=API_GATEWAY_QUEUE_TIMEOUT)` |
| 心跳 | ✅ | 超时发送 `: keepalive\n\n` |
| 断开 | ✅ | `BrokenPipeError` + `ConnectionResetError` 处理 |
| 清理 | ✅ | `finally: unsubscribe()` 确保资源释放 |
| **json 序列化** | ⚠️ | `json.dumps(event, default=str)` — default=str 可能吞没序列化错误 |
| **队列满** | ⚠️ | 无背压控制，SSE 客户端慢时队列可能无限增长 |

---

## 6. 路由注册分析

### `_resolve_handler()` 路径

```python
def _resolve_handler(path: str) -> callable:      # api_gateway.py:381
    import importlib
    parts = path.split(".")
    mod_path = ".".join(parts[:-1])
    func_name = parts[-1]
    mod = importlib.import_module(mod_path)
    return getattr(mod, func_name)
```

用于 `load_routes_from_yaml()` 的外部路由加载。无缓存，每次调用都 `importlib.import_module()`，在热路径上可能有性能影响。

### 匹配算法

`_match_route()` 使用线性扫描（227 条路由）。对于 `/api/card/{id}` 这种后缀匹配，使用 `endswith("/")` 判断 + 前缀匹配。**O(n)** 复杂度，在 227 条路由时不是瓶颈，但扩展到 1000+ 时会变慢。

---

## 7. 关键发现

### 7.1 🟡 SSE json.dumps 吞没错误（已修复 🔧）

```python
# 修复前: json.dumps(event, default=str) 静默吞没
# 修复后: 先尝试不带 default 的序列化，TypeError 时记录 warning 再 fallback
```

添加 `try/except TypeError` + `logger.warning` 记录无法序列化的对象。

### 7.2 🟡 路由匹配无缓存（已修复 🔧）

`_match_route()` 原为 O(n) 线性扫描 227 条路由。已改造为：
- `_route_cache: dict[method, dict[path, handler]]` 实现 O(1) 精确匹配
- `_suffix_routes: list[(method, prefix, handler)]` 处理 `/api/card/{id}` 后缀模式

### 7.3 🟡 `_resolve_handler()` 无缓存（已修复 🔧）

添加模块级 `_handler_cache: dict[str, callable]`，首次解析后缓存结果，后续 O(1) 返回。

### 7.4 ℹ️ `_Handler` 内部类 143 行

`api_gateway.py` 中 `_Handler` 内部类（继承 `BaseHTTPRequestHandler`）有 143 行代码，可实现为独立模块 `api/_handler.py`。

### 7.5 ℹ️ ApiHandlers 拆分建议

`api_handlers/__init__.py` 107 方法/836 行已在前序审查中提及。建议拆分为 `handlers/_system.py`, `_card.py`, `_agent.py`, `_cluster.py` 等。

---

## 8. 综合评价

| 维度 | 评分 | 说明 |
|------|:----:|------|
| **架构清晰度** | ⚠️ 7/10 | 洋葱中间件模型清晰，但 ApiHandlers 单文件 107 方法过重 |
| **路由管理** | ✅ 8/10 | 227 条路由集中在单一文件，可维护性好 |
| **认证安全** | ✅ 8/10 | HMAC compare_digest + header-only token |
| **SSE 实现** | ✅ 8/10 | 标准协议 + 心跳 + 资源清理 |
| **性能** | 🟡 6/10 | 路由线性扫描 O(n) + handler_resolve 无缓存 |
| **代码质量** | ⚠️ 7/10 | `default=str` 吞没错误、内部类过大 |

> **综合评分**: 7.3/10 — 架构设计合理，中间件链路干净。主要改进点：路由缓存、handler 解析缓存、SSE JSON 序列化错误可见性。
