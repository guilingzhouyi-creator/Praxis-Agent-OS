# Praxis 地基缺口施工规划

> **依据:** `docs/design/archive/reviews/foundation-audit.md`（2026-08-05 审查报告，6 处缺口均已代码复核确认）
> **项目版本:** v0.4.2 "Aether"
> **协作模型:** AGENTS.md 七域并行协作 + feature 分支 + 双绿合并
> **状态:** 规划阶段（未开工）

---

## 0. 总览

> **2026-08-05 执行状态:** 全部阶段已闭环合入主干（含承接 Agent 的 L4 实现与本 Agent 的三处接线/配置化收口）。分支均按约定保留：`feature/foundation-ports`（S0）、`feature/tui-contract-l3a-api`（S1/S2 实现载体）。

| 阶段 | 缺口 | 优先级 | 主域 | 依赖 | 状态 |
|---|---|---|---|---|---|
| **S0** | L1 端口地基（4 个 Port 抽象 + SignalType + 常量） | P0 前置 | K | 无 | ✅ 已合入（`6c82f6b`/merge `52d549c`） |
| **S1a** | 缺口 2: WebSocket 通道 | P0 | A | S0 | ✅ 已合入（`ws_bridge.py` 独立端口 8081,随网关启动） |
| **S1b** | 缺口 1: AuthPort 登录态 | P0 | A + C | S0 | ✅ 已合入（`AuthService(AuthPort)` + `/api/v2/auth/*`） |
| **S2a** | 缺口 3: RPC server | P1 | A + B | S0 | ✅ 已合入（`rpc/server.py` + 网关启动接线 `d8025b8`） |
| **S2b** | 缺口 5: Card/Approval 事件 | P1 | C | S0 | ✅ 已合入（`CARD_PENDING`/`APPROVAL_*` 事件挂接） |
| **S2c** | 缺口 4: FilesystemPort | P1 | T + A | S0 | ✅ 已合入（`fs_adapter.py` + boot 注册 `d8025b8`） |
| **S3** | 缺口 6: Hook emit | P2 | C + B | S0（可延后） | ✅ 已合入（`EventEmitHook` + `get_hook_chain()` + AgentLoop 触发 `33ec9d5`） |

**施工铁律（引自 AGENTS.md）:**

1. 每个阶段独立 `feature/foundation-*` 分支，双绿合并（feature 测试 + main 测试全绿，`--no-ff`），**合并不删分支**。
2. 阶段内若并行 agent 操作，使用 `git worktree add ../praxis-<area> feature/foundation-*` 物理隔离。
3. 共享文件（`params/*.py`、`l3/boot/`、`tests/conftest.py`、`test_layer_imports.py`）**同一时刻仅一个 writer**，S0 先落地主干。
4. 新增常量一律进 `src/l1/kernel/params/`，不硬编码。
5. 新 API 端点一律 `/api/v2/` + 在 `api_endpoints.py` 用 `register_endpoint()` 注册（不手改 `API_ROUTES` 分类）。
6. 每阶段验证门：层导入测试 + params 合规 + 域内测试 + 全量基线 + ruff。

---

## S0 — L1 端口地基（K 域，P0 前置）

> 分支: `feature/foundation-ports`（K 域独占，合入主干后 S1/S2 才可开工）

### S0.1 `src/l1/kernel/ports.py` — 新增 4 个端口抽象

当前 8 个 `*Port(ABC)`（Transport / Channel / EventBus / Worker / I18n / CardRegistry / MonitorBus / LLM），缺 4 个：

| 新增端口 | 抽象方法 |
|---|---|
| `AuthPort` | `issue_token(identity, ttl)` / `verify_token(token)` / `revoke_token(token)` / `refresh_token(token)` |
| `WebSocketPort` | `upgrade(request)` → conn / `recv(conn)` / `send(conn, msg)` / `close(conn)` / `broadcast(event, data)`（**审查修复 `8a5b2fe`：显式连接句柄模型**，每实例可服务多客户端，无隐式共享状态） |
| `RpcServerPort` | `register_handler(method, fn)` / `call(method, params)` / `notify(method, params)` |
| `FilesystemPort` | `read(path)` / `write(path, content)` / `list_tree(root)` / `watch(root, cb)` |

遵循现有端口风格：`ABC` + 抽象方法 + `register_port("name", impl)` / `get_port("name")`（见 `wiring.py` 既有模式）。

### S0.2 `src/l1/kernel/event.py` — SignalType 扩展

`SignalType` 当前 17 成员，增加 3 个（见缺口 5 需求）：

```python
CARD_PENDING = auto()       # card 进入 pending 队列
APPROVAL_REQUIRED = auto()  # card 被审批门拦截
APPROVAL_RESPONDED = auto() # 审批响应已提交
```

注意：`emit_event()` 与 `emit_signal()` 双通道——事件总线广播用 `emit_signal(SignalType.X, ...)` 时需确认 SSE `_broadcast` 监听的是 signal 通道（S1a 时联调）。

### S0.3 `src/l1/kernel/params/api.py` — 新增常量

| 常量 | 建议默认值 | 说明 |
|---|---|---|
| `RPC_SERVER_PORT` | `42110` | RPC server 监听端口（缺口 3，既有常量，服务器已接线） |
| `AUTH_TOKEN_TTL_SECONDS` | `86400` | 登录 token 有效期（缺口 1） |

> WS 缺口 2：`src/l4/ws/ws_bridge.py` 为同步直发模型（`conn.send()`，无每客户端队列），
> 镜像 `SSE_QUEUE_MAXSIZE` 的 `WS_MAX_QUEUED_PER_CLIENT` 无自然消费者，已删除；
> 若后续引入每客户端有界队列再恢复该常量。

> 当前 `params/api.py` 无任何 RPC/WS 端口常量，必须补（硬编码端口会被 params-compliance 拦截）。

### S0.4 验证门

```bash
python -m pytest tests/infra/test_params_compliance.py -x -q
python -m pytest tests/infra/test_layer_imports.py -x -q
python -m pytest tests/l1/ -x -q          # kernel 域测试
python tests/runner.py                    # 全量基线
ruff check src/l1/kernel/
```

---

## S1a — 缺口 2: WebSocket 通道（A 域，P0）

> 分支: `feature/foundation-ws`（依赖 S0 合入）

### 文件改动

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l1/kernel/ports.py` | 编辑 | `WebSocketPort` 已在 S0 定义，此处仅确认 |
| `src/l4/ws/__init__.py` | 新建 | WS 包 |
| `src/l4/ws/ws_bridge.py` | 新建 | 实现 `WebSocketPort`，镜像 `sse_bridge.py` 的客户端注册表 + EventBus 订阅结构 |
| `src/l4/api/api_routes.py` | 编辑 | 新增 `("GET", "/api/v2/ws", ...)` upgrade 端点 |
| `src/l4/api/api_gateway.py` | 编辑 | `_Handler` 加 `Upgrade: websocket` 分支（`do_GET` 内检测 header） |
| `src/l4/api/api_endpoints.py` | 编辑 | `register_endpoint("GET", "/api/v2/ws", ...)` 注册分类 |
| `pyproject.toml` | 编辑 | 新增服务端 WS 依赖 |

### 技术风险与决策点

- **`api_gateway._Handler` 基于同步 `http.server.BaseHTTPRequestHandler`**，无原生 upgrade 支持。两条路线：
  - **路线 A（推荐）:** 在 `do_GET` 检测到 `Upgrade: websocket` 后，将 `self.connection` socket 移交 `ws_bridge` 的独立异步/线程循环处理，HTTP 层只负责握手。改动面小，复用现有网关端口。
  - **路线 B:** WS 监听独立端口（新增 `PRAXIS_WS_PORT`），前端连 `ws://host:wsport`，与 API 网关解耦。隔离性更好但多一个端口要暴露。
- **依赖:** `pyproject.toml` 目前只有 `websocket-client>=1.0`（客户端）。服务端需要 `websockets` 或手写 RFC 6455 握手+帧（不推荐手写，帧掩码/分片易错）。**决策：新增 `websockets` 服务端依赖**，或采用路线 A 时在网关线程内用标准库手写握手（仅掩码+单帧，工作量可控，但需评审）。
- **SSE 联动:** `sse_bridge.ensure_active()` 在网关启动时调用；WS bridge 需同样在 `ApiGateway.start()` 挂载，保证事件双通道（SSE 下行 + WS 双向）。

### 消息协议（沿用审查报告建议）

```json
{"type": "subscribe", "events": ["card.pending", "approval.required"]}
{"type": "rpc", "method": "card.submit", "params": {...}}
→ 后端
{"type": "event", "event": "card.pending", "data": {...}}
{"type": "rpc.result", "method": "card.submit", "data": {...}}
```

### 验证门

```bash
python -m pytest tests/infra/test_layer_imports.py -x -q
python -m pytest tests/l4/ -x -q            # 含 ws_bridge 新测试
python -m pytest tests/l3/ -x -q            # SSE/事件联动
python tests/runner.py
```

新增测试：握手升级、订阅/退订、事件推送、队列满降级。

---

## S1b — 缺口 1: AuthPort 登录态（A + C 域，P0）

> 分支: `feature/foundation-auth`（依赖 S0）

### 文件改动

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l4/vault/auth.py` | 编辑 | `AuthService` 实现 `AuthPort`：`issue_token` / `verify_token` / `revoke_token` / `refresh_token`（HMAC + `AUTH_TOKEN_SECRET` + 过期时间；吊销表放 vault） |
| `src/l3/services/central_security.py` | 编辑 | 第 3 步（**实际第 103 行**）改用 `get_port("auth").verify_token(user_token)`，替换硬编码 `"auth verify_token not implemented"` |
| `src/l4/api/api_routes.py` | 编辑 | 新增 `/api/v2/auth/login|logout|refresh` 路由 |
| `src/l4/api/api_handlers/` | 编辑 | 新增 `auth` handler（或 `api_handlers_auth.py`） |
| `src/l4/api/api_endpoints.py` | 编辑 | `register_domain("auth", ...)` + 注册 3 个端点 |
| `src/l1/kernel/params/api.py` | 编辑 | `AUTH_TOKEN_TTL_SECONDS`（S0 已加，确认值） |

### 注意

- `central_security.py:103` 是文档中唯一一处 `"verify_token not implemented"` 硬编码；改后需保证无 token 时**降级为放行/拒签策略可配置**（`config/praxis.yaml` `security.auth_required`），避免未配置 AuthService 时全盘阻断。
- `api_gateway._auth_ok()`（`api_gateway.py:274`）目前是静态 token 校验，登录体系上线后保持兼容：`Authorization: Bearer <jwt>` 与现有 `X-API-Token` 双通道。
- 新增测试：签发/校验/吊销/刷新生命周期、过期 token 拒绝、`central_security` 集成测试（带 token 放行、无 token 按策略处理）。

### 验证门

```bash
python -m pytest tests/l4/ -x -q
python -m pytest tests/l3/ -x -q            # central_security 用例
python tests/runner.py
```

---

## S2a — 缺口 3: RPC server（A + B 域，P1）

> 分支: `feature/foundation-rpc`（依赖 S0）

### 文件改动

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l4/rpc/server.py` | 新建 | `RpcServer`：`asyncio.start_server` 监听 `RPC_SERVER_PORT`（既有常量，42110），`RpcMessage.method` 路由到 `register_handler` 注册的 handler，复用 `RpcTransport.send/recv`（4 字节长度前缀 + JSON，已有） |
| `src/l1/kernel/ports.py` | 编辑 | `RpcServerPort` 已在 S0，`wiring.py` 注册实现 |
| `src/l3/boot/wiring.py` | 编辑 | `wire_defaults()` 中 `register_port("rpc_server", RpcServer(...))` |
| `src/l4/api/api_gateway.py` | 编辑 | `start()` 时同步启动 RPC server（独立线程/进程） |
| `src/l1/kernel/params/api.py` | 已存在 | `RPC_SERVER_PORT`（既有常量，S0 曾新增重复的 `PRAXIS_RPC_PORT` 已移除，统一单一来源） |

### 注意

- `RpcTransport` / `RpcMessage` / `protocol.py` 已就绪（38 行 transport 完整），**只缺 server 骨架**——改动面小，属"协议先行、实现后补"的收尾。
- handler 返回需兼容 `RpcMessage.response(req, data)` 的 `rsp:<method>` 约定。
- 新增测试：起 server → `register_handler` → `call` 往返、未知 method 返回 error、连接断线清理。

### 验证门

```bash
python -m pytest tests/l4/ -x -q
python -m pytest tests/l3/ -x -q            # wiring 测试
python tests/runner.py
```

---

## S2b — 缺口 5: Card/Approval 事件（C 域，P1）

> 分支: `feature/foundation-card-events`（依赖 S0 的 SignalType 扩展）

### 文件改动

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l3/card/pending_queue.py` | 编辑 | `enqueue()`（第 118 行）在现有 `emit_signal(EVENT_TASK_ASSIGN, ...)` 之外，增发 `emit_signal(SignalType.CARD_PENDING, ...)`（sender="pending_queue"，data 含 card_id/msg_id） |
| `src/l3/card/approval_gate.py` | 编辑 | `request()`（**注意：方法名是 `request` 不是文档附录 B 写的 `hold`**）内发 `APPROVAL_REQUIRED`；`respond()` 内发 `APPROVAL_RESPONDED`（approved 结果进 data） |

### 注意

- 审查报告中附录 B 写的 `hold()` 与代码不符，实际是 `request()` / `respond()`——按实际方法名施工。
- SSE 自动广播已具备（`_broadcast`），事件挂接后即自动推到前端，无需额外 SSE 改动。
- 新增测试：enqueue 发 CARD_PENDING、request/respond 发对应事件、事件 data 字段完整性。

### 验证门

```bash
python -m pytest tests/l3/card/ -x -q
python -m pytest tests/l1/ -x -q            # SignalType 枚举
python tests/runner.py
```

---

## S2c — 缺口 4: FilesystemPort（T + A 域，P1）

> 分支: `feature/foundation-fs-port`（依赖 S0）

### 文件改动

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l3/services/fs.py` | 编辑 | 文件读写/树/监听改走 `get_port("fs")`；现有 `watch_start`（Path + 轮询）可作为默认 adapter 实现 |
| `src/l3/services/file_editor.py` | 编辑 | `Path.write_text` 等直接 IO 改走端口（或保留为默认 adapter 内部实现，视接口粒度） |
| `src/l1/kernel/ports.py` | 编辑 | `FilesystemPort` 已在 S0 |
| `src/l4/api/api_routes.py` | 编辑 | 新增 `/api/v2/fs/tree`、`/api/v2/fs/read`、`/api/v2/fs/watch`（注意与现有 `/api/v2/fs/edit|patch|history` 不冲突） |
| `src/l4/api/api_endpoints.py` | 编辑 | 注册 3 个新端点 |

### 注意

- `vfs.py` 已有 `VFS` 类（mount/read/write/list/proc_path）——端口默认 adapter 可直接包装 VFS，不必重新实现安全层。
- 现有 fs 端点（edit/batch-edit/history/undo/redo/patch*）不受影响，新端点只补 tree/read/watch。
- 新增测试：tree/read/watch 端点、端口 adapter 切换、VFS 包装回归。

### 验证门

```bash
python -m pytest tests/l3/services/ -x -q
python -m pytest tests/l4/ -x -q
python -m l4.api.api_endpoints        # 端点 manifest 校验（contract versioning）
python tests/runner.py
```

---

## S3 — 缺口 6: Hook emit（C + B 域，P2）

> 分支: `feature/foundation-hook-emit`（可延后，前端工具调用可视化需求出现时再补）

### 文件改动

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l3/services/hook.py` | 编辑 | **方案 A（推荐）:** 新增 `EventEmitHook(LifecycleHooks)` 子类，`turn_complete` → `get_bus().emit_event("turn.complete", {"result": result, "elapsed": elapsed})`，`on_error` → `"turn.error"`，`session_end` → `"session.end"`；**不改基类 `pass`** |
| `src/l3/boot/wiring.py` | 编辑 | boot 时 `hook_chain.add(EventEmitHook())` |

### 注意

- 基类 `LifecycleHooks` 的 `pass` 是默认实现，**不动**（影响所有现有 hook 子类）；新增子类 + 显式挂载，可独立开关。
- 事件名用 `emit_event`（自动注册字符串类型），与 AGENTS.md 中 `skill_mutated` 的惯例一致。
- 新增测试：EventEmitHook 触发后 EventBus 收到对应事件。

### 验证门

```bash
python -m pytest tests/l3/services/ -x -q
python tests/runner.py
```

---

## 1. 分支与合并路线图

```
main
├── feature/foundation-ports        (S0, K)      → merge --no-ff, 保留分支
├── feature/foundation-ws           (S1a, A)     → merge --no-ff, 保留分支
├── feature/foundation-auth         (S1b, A+C)   → merge --no-ff, 保留分支
├── feature/foundation-rpc          (S2a, A+B)   → merge --no-ff, 保留分支
├── feature/foundation-card-events  (S2b, C)     → merge --no-ff, 保留分支
├── feature/foundation-fs-port      (S2c, T+A)   → merge --no-ff, 保留分支
└── feature/foundation-hook-emit    (S3, C+B)    → merge --no-ff, 保留分支
```

- S1a/S1b 可并行（不同文件域：ws 全在 A，auth 跨 A+C 但文件不重叠）；S2a/S2b/S2c 可并行。
- 每分支开工前先 `git fetch origin && git merge origin/main` 对齐 S0。
- 每分支合入前双绿：feature 分支全测 + main 全测（`tests/runner.py`）。

## 2. 风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| `_Handler` 同步模型无原生 WS upgrade | 高 | S1a 决策点：socket 移交独立循环（路线 A）或独立端口（路线 B）；建议先做路线 A 最小握手验证 |
| 服务端 WS 依赖缺失（仅 websocket-client） | 高 | 新增 `websockets` 依赖；或标准库手写握手（需评审） |
| 无 token 时 central_security 全盘阻断 | 中 | `security.auth_required` 配置开关，默认降级策略 |
| `api_gateway._auth_ok` 与登录体系双通道兼容 | 中 | Bearer + X-API-Token 并存，回归测试 |
| params-compliance 拦截未注册常量 | 低 | 所有新常量 S0 统一进 params/ |
| 契约版本化：新端点未注册 manifest | 低 | 每阶段跑 `python -m l4.api.api_endpoints` |

---

**规划结束。** S0 是唯一阻塞项，落地后 S1/S2 各分支可并行施工。
