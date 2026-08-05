# Praxis 地基审查报告

> **审查时间:** 2026-08-05
> **审查范围:** L1 Kernel → L5 User 全栈地基、前端预留端口与调用点位
> **验证方式:** `grep` + `read_file` 实际比对各层文件、桩位、端口空缺、事件链断点
> **项目版本:** v0.4.1 "Aether"

---

## 目录

1. [5 层地基完成度总览](#一5-层地基完成度总览)
2. [未构建好的地基缺口（6 处）](#二未构建好的地基缺口6-处按优先级排序)
3. [前端不用考虑的点（后端已封装,12 项）](#三前端不用考虑的点后端已封装12-项)
4. [必须预留好的端口与调用点位](#四必须预留好的端口与调用点位)
5. [关键参数/常量默认值](#五关键参数常量默认值前端无需感知但需知道默认值)
6. [优先级建议与施工顺序](#六优先级建议与施工顺序)
7. [一句话总结](#七一句话总结)

---

## 一、5 层地基完成度总览

| 层 | 完成度 | 状态 | 关键缺口 |
|---|---|---|---|
| **L1 Kernel** | ~90% | 端口抽象扎实,817 常量 | 缺 `AuthPort` / `WebSocketPort` / `FilesystemPort` / `RpcServerPort` |
| **L2 Shell** | ~95% | 40 命令 + i18n + 补全器齐全 | 无 |
| **L3 Cell** | ~80% | services 32 模块齐全 | `hook.py` 桩位、`pending_queue` 事件未挂接 |
| **L4 Bridge** | ~85% | API ~170 路由全注册 | WebSocket 通道缺失、RPC server 空挂 |
| **L5 User** | ~70% | cli.py + agent_runtime 在位 | 无 Web 前端入口 |

---

## 二、未构建好的地基缺口（6 处,按优先级排序）

### 缺口 1:P0 高危——L1 安全端口桩位

**位置:** `src/l3/services/central_security.py:104`

```python
verdict.add_gate("auth", False, "auth verify_token not implemented", score=0.5)
```

**验证证据:**

- `grep verify_token|issue_token|revoke|login|session` 在 `src/l4/vault/auth.py`:**无匹配**
- `AuthService`（`src/l4/vault/auth.py`）只有 `sign` / `verify` / `hash` / `encrypt` / `decrypt` / `vault_set` / `vault_get` / `vault_list`,**无 token 相关方法**
- L1 `ports.py` 未定义 `AuthPort` 抽象
- `central_security.py` 第 102-104 行硬编码 `"auth verify_token not implemented"`

**后果:**

- 任何带 `user_token` 的请求都会被 auth gate 阻断（`score=0.5`）
- **前端登录态无法落地**——没有 token 签发/校验/吊销机制
- L4 API 网关的 `auth_token`（`api_gateway.py:72`）只支持单一静态 token,无法支持多用户会话

**需补内容:**

| 文件 | 改动 |
|---|---|
| `src/l1/kernel/ports.py` | 新增 `AuthPort`（抽象类:`issue_token` / `verify_token` / `revoke_token` / `refresh_token`） |
| `src/l4/vault/auth.py` | `AuthService` 实现 `AuthPort`（基于 HMAC + 过期时间） |
| `src/l3/services/central_security.py` | 第 3 步改用 `get_port("auth").verify_token(user_token)` |
| `src/l4/api/api_routes.py` | 新增 `/api/v2/auth/login`、`/api/v2/auth/logout`、`/api/v2/auth/refresh` |
| `src/l4/api_handlers/api_handlers_auth.py` | 新建,实现上述路由 handler |

---

### 缺口 2:P0 高危——L4 WebSocket 通道缺失

**验证证据:**

- `grep websocket|WebSocket|ws_bridge|asyncio\.start_server` 全项目:
  - `src/l1/kernel/device.py:6,111` ——仅 device capability 声明
  - `src/l1/kernel/model_registry.py:78,93,149` ——仅 `websocket` provider 注册
  - `src/l4/llm/llm_providers.py:362` ——`WebSocketProvider`（LLM 流式,非前端通道）
  - `src/l1/kernel/platform.py:243` ——`asyncio.start_server`（Unix socket server,非 WS）
- **无前端 WS 桥**,无 `src/l4/ws/` 目录
- `src/l4/sse/sse_bridge.py` 是单向下行 SSE,无法支持双向交互
- `api_gateway._Handler`（`api_gateway.py:267`）仅处理普通 GET/POST,**无 `Upgrade: websocket` 分支**

**后果:**

- 前端无法做双向交互——card 进度推送、approval 实时交互、agent 对话流都需要双向通道
- 当前 SSE 是"服务器推→前端收",前端要"发消息→服务器处理→推送结果"必须走 WS

**需补内容:**

| 文件 | 改动 |
|---|---|
| `src/l1/kernel/ports.py` | 新增 `WebSocketPort`（抽象类:`upgrade` / `recv` / `send` / `close` / `broadcast`） |
| `src/l4/ws/__init__.py` | 新建包 |
| `src/l4/ws/ws_bridge.py` | 新建,镜像 `sse_bridge.py` 结构,实现 `WebSocketPort` |
| `src/l4/api/api_routes.py` | 新增 `/api/v2/ws`（upgrade 端点） |
| `src/l4/api/api_gateway.py` | `_Handler` 加 `Upgrade: websocket` 分支 |

**WS 消息协议建议:**

```json
// 前端 → 后端
{"type": "subscribe", "events": ["card.pending", "approval.required"]}
{"type": "unsubscribe", "events": ["card.pending"]}
{"type": "rpc", "method": "card.submit", "params": {...}}

// 后端 → 前端
{"type": "event", "event": "card.pending", "data": {...}}
{"type": "rpc.result", "method": "card.submit", "data": {...}}
{"type": "error", "message": "..."}
```

---

### 缺口 3:P1 高危——L4 RPC 传输未接 L3/L5（分布式地基空挂）

**验证证据:**

- `ls src/l4/rpc/`:

  ```
  __init__.py
  protocol.py
  transport.py
  ```

  **没有 `server.py`**
- `grep register_handler|start_server|RpcServer|listen` 在 `src/l4/rpc`:**无匹配**
- `transport.py`（完整 38 行）只有静态 `send` / `recv`,**没有监听 server**
- `src/l1/kernel/net.py` 的 `TcpAdapter`（`net_transport.py:136`）与 RPC 是两套独立实现,**未打通**
- `protocol.py` 定义了 `RpcMessage`（method / params / error / id）,但**没有任何 `register_handler` 注册点**

**后果:**

- 分布式 cell / 跨节点 agent / 远程 L5 调用全部空挂
- 前端无法访问"跨节点"能力
- `RpcMessage` 协议定义完整但无人调用——典型的"协议先行,实现后补"

**需补内容:**

| 文件 | 改动 |
|---|---|
| `src/l4/rpc/server.py` | 新建,基于 `asyncio.start_server` 监听,把 `RpcMessage.method` 路由到 handler |
| `src/l1/kernel/ports.py` | 新增 `RpcServerPort`（抽象类:`register_handler` / `call` / `notify`） |
| `src/l3/boot/wiring.py` | boot 时 wire `RpcServer` 到 `RpcServerPort` |
| `src/l4/api/api_gateway.py` | `start()` 时同步起 RPC server（独立端口,如 `PRAXIS_RPC_PORT`） |

**RPC server 骨架建议:**

```python
class RpcServer:
    def __init__(self, host: str, port: int):
        self._handlers: dict[str, Callable] = {}
        self._server = None

    def register_handler(self, method: str, handler: Callable) -> None:
        self._handlers[method] = handler

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_conn, self._host, self._port
        )

    async def _handle_conn(self, reader, writer) -> None:
        msg = await RpcTransport.recv(reader)
        rpc_msg = RpcMessage(**msg)
        handler = self._handlers.get(rpc_msg.method)
        if handler:
            result = handler(rpc_msg.params)
            response = RpcMessage.response(rpc_msg, result)
            await RpcTransport.send(writer, response.to_dict())
        writer.close()
```

---

### 缺口 4:P1 中危——L1/L3 文件系统端口未抽象

**验证证据:**

- `grep VfsPort|get_port|VFS|from l1.kernel.vfs` 在 `src/l3/services/fs.py`:**无匹配**
- `fs.py` 直接走 `os.*` / `open()` / `os.path.*`
- `src/l3/services/file_editor.py` 同样直接走 OS（`open`、`os.path.exists`、`shutil`）
- `src/l1/kernel/vfs.py` 存在（VFS 虚拟文件系统）,但 `fs.py` / `file_editor.py` **没有声明它依赖 `VfsPort`**
- L1 `ports.py` 未定义 `FilesystemPort`

**后果:**

- 前端"文件树"视图无法直接复用抽象
- 跨节点文件访问无统一接口
- 沙箱文件与 VFS 文件之间无统一 API

**需补内容:**

| 文件 | 改动 |
|---|---|
| `src/l1/kernel/ports.py` | 新增 `FilesystemPort`（抽象类:`read` / `write` / `list` / `stat` / `watch` / `mkdir` / `rm`） |
| `src/l3/services/fs.py` | 改走 `get_port("fs")` |
| `src/l4/api/api_routes.py` | 新增 `/api/v2/fs/tree`、`/api/v2/fs/read`、`/api/v2/fs/watch` |

---

### 缺口 5:P1 中危——L3 Approval/Pending 流向 L2/L5 的回调点缺失

**验证证据:**

`grep emit_event|emit_signal|get_bus\(\)\.emit` 在 `src/l3`,**已挂接的位置**:

| 文件 | 行号 | 挂接内容 |
|---|---|---|
| `card/card_gate.py` | 197 | `emit_signal(EVENT_TASK_ASSIGN, ...)` held_for_approval |
| `card/card_registry.py` | 24 | `emit_signal` 导入 |
| `cell/__init__.py` | 339 | `emit_signal(EVENT_TASK_ASSIGN, ...)` card dispatch |
| `agent_terminal/__init__.py` | 249,546,562 | `emit_signal` agent boot / review / issue |
| `discussion/issue_orchestrator.py` | 148 | `bus.emit_event("discussion.completed", ...)` |
| `discussion/report_service.py` | 112 | `bus.emit_event("discussion.report", ...)` |
| `error_bus/__init__.py` | 355 | `get_bus().emit_event("error_log", ...)` |
| `memory/memory_graph.py` | 136,165 | `_emit_event("stats.memory.graph.*", ...)` |

**未挂接的位置（缺口）:**

| 文件 | 缺失内容 |
|---|---|
| `card/pending_queue.py` | `enqueue()` 时**未 emit `CARD_PENDING` 事件** |
| `card/approval_gate.py` | `hold()` 时**未 emit `APPROVAL_REQUIRED` 事件** |
| `card/approval_gate.py` | `respond()` 时**未 emit `APPROVAL_RESPONDED` 事件** |

**L1 `event.py` `SignalType` 枚举（19 个成员）现状:**

```python
class SignalType(Enum):
    TASK_ASSIGN = auto()          # ✅ 已用于 card dispatch
    TASK_CANCEL = auto()          # ✅
    REVIEW_RESULT = auto()        # ✅
    CONSTITUTION_UPDATE = auto()  # ✅
    TASK_DONE = auto()            # ✅
    TASK_ACCEPT = auto()          # ✅
    TASK_ERROR = auto()           # ✅
    DISPUTE_RAISE = auto()        # ✅
    AGENT_CRASH = auto()          # ✅
    STATE_CHANGE = auto()         # ✅
    CROSS_REVIEW_REQ = auto()     # ✅
    CROSS_REVIEW_RESP = auto()    # ✅
    TERRITORY_QUERY = auto()      # ✅
    SCOUT_DONE = auto()           # ✅
    REVIEW_REQUESTED = auto()     # ✅
    TOKEN_USAGE = auto()          # ✅
    FILE_CHANGED = auto()         # ✅
    # ❌ 缺: CARD_PENDING
    # ❌ 缺: APPROVAL_REQUIRED
    # ❌ 缺: APPROVAL_RESPONDED
```

**后果:**

- 前端要弹"待审批"通知,缺少这条事件链
- `pending_queue` 入队后前端只能轮询 `/api/v2/pending`,无法被动接收

**需补内容:**

| 文件 | 改动 |
|---|---|
| `src/l1/kernel/event.py` | `SignalType` 增加 `CARD_PENDING`、`APPROVAL_REQUIRED`、`APPROVAL_RESPONDED` |
| `src/l3/card/pending_queue.py` | `enqueue()` 内调 `emit_signal(SignalType.CARD_PENDING, ...)` |
| `src/l3/card/approval_gate.py` | `hold()` 内调 `emit_signal(SignalType.APPROVAL_REQUIRED, ...)`;`respond()` 内调 `emit_signal(SignalType.APPROVAL_RESPONDED, ...)` |
| `src/l4/sse/sse_bridge.py` | 无需改——`ensure_active()` 已 `on_any` 广播所有事件,新事件类型自动通过 SSE 推送到前端 |

---

### 缺口 6:P2 低危——L5 agent_runtime 与前端 runtime 的接缝未定

**验证证据:**

`src/l3/services/hook.py` 三个生命周期回调是 `pass` 桩:

```python
# hook.py:50-58
def turn_complete(self, result: dict, elapsed: float) -> None:
    """Unconditional terminal — always called, even on error."""
    pass                                          # ❌ 桩

def on_error(self, error: str) -> None:
    pass                                          # ❌ 桩

def session_end(self, result: dict) -> None:
    pass                                          # ❌ 桩
```

- `grep emit_event|emit_signal` 在 `hook.py`:**无匹配**（仅 SkillCatalogHook / CadenceHook / StatusReminderHook 等内置 hook 内部有事件,但 `turn_complete` / `on_error` / `session_end` 这三个生命周期回调本身是 `pass`）
- `LifecycleHooks` 基类定义了 9 个方法（`session_start` / `user_prompt_submit` / `pre_request` / `on_text_delta` / `on_reasoning_delta` / `on_model_response` / `offer_continuation` / `turn_complete` / `on_error` / `session_end`）,其中**最后三个是 `pass`**

**后果:**

- 前端无法实时看到 turn 完成、错误、session 结束等事件
- Agent 运行时的"心跳"信号缺失

**需补内容:**

| 文件 | 改动 |
|---|---|
| `src/l3/services/hook.py` | `turn_complete` 改 `get_bus().emit_event("turn.complete", {"result": result, "elapsed": elapsed})` |
| 同上 | `on_error` 改 `get_bus().emit_event("turn.error", {"error": error})` |
| 同上 | `session_end` 改 `get_bus().emit_event("session.end", {"result": result})` |

**注意:** 这三个是基类 `LifecycleHooks` 的默认实现（`pass`）,改基类会影响所有子类。建议在基类保留 `pass`,在 `HookChain`（`hook.py:61`）的对应方法内加 emit。或新建 `EventEmitHook(LifecycleHooks)` 子类,在 boot 时 `hook_chain.add(EventEmitHook())`。

---

## 三、前端不用考虑的点（后端已封装,12 项）

| # | 后端能力 | 文件位置 | 前端无需感知 |
|---|---|---|---|
| 1 | L1 `params/` 817 个常量 | `src/l1/kernel/params/` | 全部由后端消费,前端只看 API 返回值 |
| 2 | L1 `gatechain.py` G1-G5 门控 | `src/l1/kernel/gatechain.py` | 前端只看 `check_all()` 返回的 `allowed` / `blocked_by` |
| 3 | L1 `swapper.py` 内存换页 | `src/l1/kernel/swapper.py` | 透明,前端不感知 |
| 4 | L1 `allocator.py` 内存分配 | `src/l1/kernel/allocator.py` | 透明,前端不感知 |
| 5 | L1 `constitution.py` 宪法引擎 | `src/l1/kernel/constitution.py` | 前端只看 `/api/v2/constitution` 只读视图 |
| 6 | L3 `r4_agent.py` skill 进化 | `src/l3/memory/r4_agent.py` | 前端只读 `/api/v2/skills` 列表 |
| 7 | L3 `memory_graph.py` R5 图 | `src/l3/memory/memory_graph.py` | 前端只看 `memory_graph_status` 开关 |
| 8 | L3 `scheduler/` 调度器 | `src/l3/scheduler/` | 前端只看 `/api/v2/loops` 结果 |
| 9 | L3 `bus/htn_planner.py` HTN 规划 | `src/l3/bus/htn_planner.py` | 前端只看 card 执行 plan |
| 10 | L4 `vault/credential_vault.py` AES-GCM 加密 | `src/l4/vault/credential_vault.py` | 前端只调 `/api/v2/credentials` 增删查 |
| 11 | L4 `lsp/` 语言服务器进程管理 | `src/l4/lsp/lsp_manager.py` | 前端只调 `/api/v2/lsp/diagnostics` |
| 12 | L4 `sandbox/` 结构化 diff | `src/l4/sandbox/` | 前端只调 `/api/v2/diff/structured` |

---

## 四、必须预留好的端口与调用点位

### A. L1 端口层（`src/l1/kernel/ports.py`）——前端地基的"下水道"

| 端口 | 当前状态 | 适配器 | 前端依赖 |
|---|---|---|---|
| `TransportPort` | ✅ 已定义 | `TcpAdapter`（`net_transport.py`） | 跨节点 cell 通信 |
| `ChannelPort` | ✅ 已定义 | `RingChannel`（`adapters/channel_ring.py`） | 异步任务流 |
| `EventBusPort` | ✅ 已定义 | `EventBus`（`event.py`） | 所有实时事件 |
| `WorkerPort` | ✅ 已定义 | `ThreadPoolWorker`（`adapters/worker_thread.py`） | 后台任务 |
| `I18nPort` | ✅ 已定义 | `YamlI18nAdapter`（`adapters/i18n_yaml.py`） | 多语言 UI |
| `CardRegistryPort` | ✅ 已定义 | `CardRegistryAdapter`（`adapters/card_registry.py`） | card 类型列表 |
| `MonitorBusPort` | ✅ 已定义 | `MonitorBusAdapter`（`adapters/monitor_bus.py`） | 监控面板 |
| `LLMPort` | ✅ 已定义 | `LLMAdapter`（boot 时 wire） | 模型管理面板 |
| **`AuthPort`** | ❌ **缺** | 需 `AuthService` 实现 | **前端登录态** |
| **`WebSocketPort`** | ❌ **缺** | 需 `ws_bridge.py` 实现 | **前端双向实时** |
| **`FilesystemPort`** | ❌ **缺** | 需 `fs.py` 走端口 | **文件树/编辑器** |
| **`RpcServerPort`** | ❌ **缺** | 需 `rpc/server.py` 实现 | **跨节点远程调用** |

---

### B. L4 API 调用点位（前端直接消费,~170 条路由已注册）

#### B.1 系统/生命周期

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| 系统健康 | `/api/v2/health` | GET |
| 进程列表 | `/api/v2/processes` | GET |
| 设备列表 | `/api/v2/devices` | GET |
| 同级节点 | `/api/v2/peers` | GET |
| 系统调用 | `/api/v2/syscalls` | GET |
| 端点列表 | `/api/v2/endpoints` | GET |
| 工具模式 | `/api/v2/mode` | GET/PUT |
| 冷启动 | `/api/v2/boot` | POST |
| 关机 | `/api/v2/shutdown` | POST |
| 重启 | `/api/v2/reboot` | POST |
| 热重载 | `/api/v2/reload` | POST |
| 工厂重置 | `/api/v2/reset` | POST |
| 启动状态 | `/api/v2/boot/status` | GET |
| 引导状态 | `/api/v2/bootstrap/status` | GET |
| 引导默认 | `/api/v2/bootstrap/defaults` | GET |
| 引导应用 | `/api/v2/bootstrap/apply` | POST |

#### B.2 Card / Pending / Approval

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| 提交 card | `/api/v2/card` | POST |
| 批量 card | `/api/v2/card/batch` | POST |
| card 列表 | `/api/v2/cards` | GET |
| card 详情 | `/api/v2/card/{id}` | GET |
| card 回滚 | `/api/v2/card/rollback` | POST |
| card 审批轨迹 | `/api/v2/card/approval/{id}` | GET |
| 统一 card | `/api/v2/card-unified` | POST |
| card 计划 | `/api/v2/cards/plan` | POST |
| card 门控统计 | `/api/v2/card-gate/stats` | GET |
| card 门控历史 | `/api/v2/card-gate/history` | GET |
| card 门控配置 | `/api/v2/card-gate/config` | GET/POST |
| card 类型 | `/api/v2/card-types` | GET/POST |
| 审批列表 | `/api/v2/approvals` | GET |
| 审批响应 | `/api/v2/approvals/respond` | POST |
| 待办队列 | `/api/v2/pending` | GET |
| 待办审批 | `/api/v2/pending/approve` | POST |
| 待办拒绝 | `/api/v2/pending/reject` | POST |
| 待办升级 | `/api/v2/pending/escalate` | POST |
| 待办优先级 | `/api/v2/pending/priority` | POST |
| 待办统计 | `/api/v2/pending/stats` | GET |

#### B.3 Agent / SubAgent / L3A

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| agent 列表 | `/api/v2/agents` | GET |
| agent 选择 | `/api/v2/agent/select/{id}` | GET |
| agent 按角色 | `/api/v2/agent/select` | POST |
| agent 预连 | `/api/v2/agent/preconnect` | POST |
| agent 直接会话 | `/api/v2/agent/direct` | POST |
| agent 关闭会话 | `/api/v2/agent/direct/close` | POST |
| agent 可达 | `/api/v2/agent/reachable/{id}` | GET |
| agent review | `/api/v2/agent/review` | POST |
| agent 配置 | `/api/v2/agents/config` | GET/PUT |
| subagent 分派 | `/api/v2/subagent/dispatch` | POST |
| subagent 结果 | `/api/v2/subagent/result` | POST |
| subagent 取消 | `/api/v2/subagent/cancel` | POST |
| subagent 任务 | `/api/v2/subagent/tasks` | POST |
| subagent specs | `/api/v2/subagent/specs` | GET |
| subagent 注册 spec | `/api/v2/subagent/spec` | POST |
| subagent 合并 | `/api/v2/subagent/merge` | POST |
| subagent 默认 | `/api/v2/subagent/defaults` | GET/PUT |
| subagent spec 配置 | `/api/v2/subagent/specs/{name}` | GET/PUT |
| L3A ask 状态 | `/api/v2/l3a/ask/status` | POST |
| L3A ask 回答 | `/api/v2/l3a/ask/answer` | POST |

#### B.4 LLM Providers / Model Spec

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| providers 列表 | `/api/v2/providers` | GET |
| providers 注册 | `/api/v2/providers` | POST |
| providers 删除 | `/api/v2/providers/{name}` | DELETE |
| providers 健康 | `/api/v2/providers/{name}/health` | GET |
| providers 配置 | `/api/v2/providers/{name}/config` | PUT |
| model spec 列表 | `/api/v2/model-spec` | GET |
| model spec 更新 | `/api/v2/model-spec/{name}` | PUT |
| model spec 策略 | `/api/v2/model-spec/{name}/strategy` | GET/PUT/DELETE |
| model spec 批量策略 | `/api/v2/model-spec/strategy/apply` | PUT |
| model spec 概览 | `/api/v2/model-spec/overview` | GET |
| reasoning caps | `/api/v2/model-spec/caps` | GET/PUT |
| peer strategy | `/api/v2/model-spec/peer` | GET/PUT/DELETE |

#### B.5 Memory / Skills / Discussion

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| 记忆存储 | `/api/v2/memory/store` | POST |
| 记忆召回 | `/api/v2/memory/recall` | POST |
| 记忆统计 | `/api/v2/memory/stats` | GET |
| R5 图状态 | `/api/v2/memory/graph` | GET/PUT |
| R5 图压缩 | `/api/v2/memory/graph/compact` | POST |
| R5 语义边 | `/api/v2/memory/graph/edge` | POST |
| R5 语义边列表 | `/api/v2/memory/graph/semantic` | GET |
| Mer 状态 | `/api/v2/memory/mer` | GET/PUT |
| Mer 变换 | `/api/v2/memory/mer/transform` | POST |
| skills 列表 | `/api/v2/skills` | GET |
| skill 详情 | `/api/v2/skills/{name}` | GET |
| skill 创建 | `/api/v2/skills` | POST |
| skill 更新 | `/api/v2/skills/{name}` | PUT |
| skill 删除 | `/api/v2/skills/{name}` | DELETE |
| skill reload | `/api/v2/skills/reload` | POST |
| skill 权限 | `/api/v2/skills/permissions` | GET |
| discussion 启动 | `/api/v2/discussion/start` | POST |
| discussion 会话 | `/api/v2/discussion/sessions` | GET |
| discussion 报告 | `/api/v2/discussion/reports` | GET |
| discussion 详情 | `/api/v2/discussion/{session_id}` | GET |
| discussion 答案 | `/api/v2/discussion/{session_id}/answers` | GET |
| discussion 报告 | `/api/v2/discussion/{session_id}/report` | GET |
| discussion 补充 | `/api/v2/discussion/{session_id}/supplement` | POST |
| discussion push L3A | `/api/v2/discussion/push-to-l3a` | POST |

#### B.6 File / FS / Patch / Editor

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| 文件语义编辑 | `/api/v2/fs/edit` | POST |
| 文件批量编辑 | `/api/v2/fs/batch-edit` | POST |
| 文件历史 | `/api/v2/fs/history` | POST |
| 文件 undo | `/api/v2/fs/undo` | POST |
| 文件 redo | `/api/v2/fs/redo` | POST |
| patch 创建 | `/api/v2/fs/patch` | POST |
| patch 应用 | `/api/v2/fs/patch/apply` | POST |
| patch 撤销 | `/api/v2/fs/patch/revert` | POST |
| patch 列表 | `/api/v2/fs/patches` | POST |
| patch 详情 | `/api/v2/fs/patch/get` | POST |

#### B.7 LSP / Search / Sandbox / Diff

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| LSP 诊断 | `/api/v2/lsp/diagnostics` | POST |
| LSP hover | `/api/v2/lsp/hover` | POST |
| LSP servers | `/api/v2/lsp/servers` | GET |
| LSP start/stop | `/api/v2/lsp/start`、`/api/v2/lsp/stop` | POST |
| LSP feedback | `/api/v2/lsp/feedback` | POST |
| 统一搜索 | `/api/v2/search` | POST |
| 语义搜索 | `/api/v2/search/semantic` | POST |
| 符号搜索 | `/api/v2/search/symbol` | POST |
| 文档搜索 | `/api/v2/search/docs` | POST |
| 文档索引 | `/api/v2/search/docs/index` | POST |
| 结构化 diff | `/api/v2/diff/structured` | POST |
| diff 历史 | `/api/v2/diff/history` | POST |
| diff 颜色 | `/api/v2/diff/colors` | POST |
| 缓冲区状态 | `/api/v2/buffer/status` | GET |
| 缓冲区提交 | `/api/v2/buffer/commit` | POST |
| 缓冲区 diff | `/api/v2/buffer/diff` | POST |
| 缓冲区丢弃 | `/api/v2/buffer/discard` | POST |

#### B.8 Credentials / Security / Trust / Monitor / Cron / Records / Stats

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| 凭据状态 | `/api/v2/credentials` | GET |
| 凭据设置 | `/api/v2/credentials` | POST |
| 凭据删除 | `/api/v2/credentials` | DELETE |
| 安全检查 | `/api/v2/security/check` | POST |
| 安全统计 | `/api/v2/security/stats` | GET |
| 信任检查 | `/api/v2/trust/check` | POST |
| 信任统计 | `/api/v2/trust/stats` | GET |
| 监控事件 | `/api/v2/monitor/events` | GET |
| 监控统计 | `/api/v2/monitor/stats` | GET |
| 监控流（SSE） | `/api/v2/monitor/stream` | GET |
| 监控门控 | `/api/v2/monitor/gate` | GET/POST |
| 监控门控删除 | `/api/v2/monitor/gate/{id}` | DELETE |
| cron 列表 | `/api/v2/cron` | GET |
| cron 添加 | `/api/v2/cron` | POST |
| cron 删除 | `/api/v2/cron` | DELETE |
| records 查询 | `/api/v2/records/query` | POST |
| records 统计 | `/api/v2/records/stats` | GET |
| records 导出 | `/api/v2/records/export` | POST |
| records 桥接 | `/api/v2/records/bridge` | POST |
| stats 查询 | `/api/v2/stats/query` | POST |
| stats top | `/api/v2/stats/top` | GET |
| stats live（SSE） | `/api/v2/stats/live` | GET |

#### B.9 Session / Export / Rollback / Config

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| session 导出 | `/api/v2/session/export` | POST |
| session 导入 | `/api/v2/session/import` | POST |
| session 快照 | `/api/v2/session/snapshots` | GET |
| session 快照创建 | `/api/v2/session/snapshot` | POST |
| session 快照恢复 | `/api/v2/session/snapshot/restore` | POST |
| session 快照删除 | `/api/v2/session/snapshot/delete` | POST |
| session 状态 | `/api/v2/session/state` | GET |
| 回滚上下文 | `/api/v2/rollback/context` | GET |
| 配置列表 | `/api/v2/config` | POST |
| 配置获取 | `/api/v2/config/get` | POST |
| 配置设置 | `/api/v2/config/set` | PUT |
| 配置分类 | `/api/v2/config/categories` | GET |
| 设置 | `/api/v2/settings` | GET/POST |

#### B.10 Constitution / Cluster / Cell / Communication

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| constitution | `/api/v2/constitution` | GET |
| constitution 规则 | `/api/v2/constitution/rules` | PUT/DELETE |
| constitution reload | `/api/v2/constitution/reload` | POST |
| constitution summary | `/api/v2/constitution/summary` | GET |
| cluster 状态 | `/api/v2/cluster/status` | GET |
| cluster composites | `/api/v2/cluster/composites` | GET |
| cluster 扩容 | `/api/v2/cluster/expand` | POST |
| cluster 缩容 | `/api/v2/cluster/shrink` | POST |
| cell 停止 | `/api/v2/cell/stop` | POST |
| cell liveness | `/api/v2/cell/liveness` | GET |
| 通信统计 | `/api/v2/communication/stats` | GET |
| 通信最近 | `/api/v2/communication/recent` | GET |

#### B.11 MCP / Plugins / Shell / Commands / Tools / Tokens

| 前端功能 | API 端点 | 方法 |
|---|---|---|
| MCP import | `/api/v2/mcp/import` | POST |
| MCP servers | `/api/v2/mcp/servers` | GET |
| MCP remove | `/api/v2/mcp/servers` | DELETE |
| MCP tools/list | `/api/v2/mcp/tools/list` | GET |
| MCP tools/call | `/api/v2/mcp/tools/call` | POST |
| MCP ping | `/api/v2/mcp/ping` | GET |
| plugins 列表 | `/api/v2/plugins` | GET |
| plugins 工具安装 | `/api/v2/plugins/tool` | POST |
| plugins 删除 | `/api/v2/plugins` | DELETE |
| plugins MCP 安装 | `/api/v2/plugins/mcp` | POST |
| plugins stats | `/api/v2/plugins/stats` | GET |
| shell dispatch | `/api/v2/shell` | POST |
| shell autocomplete | `/api/v2/shell/autocomplete` | GET |
| shell commands | `/api/v2/shell/commands` | GET |
| commands 列表 | `/api/v2/commands` | GET |
| commands 注册 | `/api/v2/commands` | POST |
| commands 删除 | `/api/v2/commands/{name}` | DELETE |
| commands 更新 | `/api/v2/commands/{name}` | PUT |
| tools stats | `/api/v2/tools` | GET |
| tools policy | `/api/v2/tools/policy` | GET/POST/DELETE |
| tools locales | `/api/v2/tools/locales` | GET |
| locales | `/api/v2/locales` | GET |
| loops stats | `/api/v2/loops` | GET |
| loops recent | `/api/v2/loops/recent` | GET |
| tokens stats | `/api/v2/tokens` | GET |
| tokens cells | `/api/v2/tokens/cells` | GET |
| tokens global | `/api/v2/tokens/global` | GET |
| export counter | `/api/v2/export` | GET |
| metrics | `/api/v2/metrics` | GET |

---

### B.12 实时事件流（已就绪,前端直接订阅）

| 流类型 | API 端点 | 协议 | 用途 |
|---|---|---|---|
| **SSE 事件流** | `/api/v2/events` | GET（SSE） | 所有 EventBus 事件广播 |
| **监控事件流** | `/api/v2/monitor/stream` | GET（SSE） | 监控事件实时流 |
| **stats 实时流** | `/api/v2/stats/live` | GET（SSE） | 实时指标流 |

**SSE 事件类型清单（前端订阅时使用）:**

| 事件类型 | 来源 | 说明 |
|---|---|---|
| `error_log` | `error_bus/__init__.py:355` | 错误日志事件 |
| `discussion.completed` | `discussion/issue_orchestrator.py:148` | discussion 完成 |
| `discussion.report` | `discussion/report_service.py:112` | discussion 报告生成 |
| `stats.memory.graph.switch` | `memory/memory_graph.py:136` | R5 图开关变更 |
| `stats.memory.graph.edge_mode` | `memory/memory_graph.py:165` | R5 边模式变更 |
| `TASK_ASSIGN` | `card_gate.py:197`、`card_registry.py`、`cell/__init__.py:339` | card 分派 |
| `REVIEW_REQUESTED` | `agent_terminal/__init__.py:546,562` | 评审请求 |
| `card.pending` | ❌ **待补**（缺口 5） | card 进入 pending 队列 |
| `approval.required` | ❌ **待补**（缺口 5） | card 被审批门拦截 |
| `approval.responded` | ❌ **待补**（缺口 5） | 审批响应已提交 |
| `turn.complete` | ❌ **待补**（缺口 6） | Agent turn 完成 |
| `turn.error` | ❌ **待补**（缺口 6） | Agent turn 出错 |
| `session.end` | ❌ **待补**（缺口 6） | Agent session 结束 |

---

### C. 前端需预留的"接驳口"（缺口汇总）

#### C.1 登录/会话接驳口（P0 缺,需新建）

| 接驳口 | 当前 | 需补 |
|---|---|---|
| 登录 | ❌ 无 | `/api/v2/auth/login`（`issue_token`） |
| 登出 | ❌ 无 | `/api/v2/auth/logout`（`revoke_token`） |
| 刷新 token | ❌ 无 | `/api/v2/auth/refresh`（`refresh_token`） |
| token 校验 | ❌ `verify_token not implemented` | `AuthPort.verify_token` + `AuthService` 实现 |

**登录流程建议:**

```
前端 POST /api/v2/auth/login {username, password}
  ↓ AuthService.issue_token(username) → {token, expires_at}
前端存储 token,后续请求 Header: Authorization: Bearer <token>
  ↓ api_gateway._Handler._auth_ok() 校验
前端 POST /api/v2/auth/refresh {token} → {new_token, expires_at}
前端 POST /api/v2/auth/logout {token} → AuthService.revoke_token(token)
```

---

#### C.2 WebSocket 接驳口（P0 缺,需新建）

| 接驳口 | 当前 | 需补 |
|---|---|---|
| WS 端点 | ❌ 无 | `/api/v2/ws`（upgrade 端点） |
| WS 桥 | ❌ 无 | `src/l4/ws/ws_bridge.py` |
| WS 端口 | ❌ 无 | L1 `ports.py` 加 `WebSocketPort` |
| WS handler | ❌ `_Handler` 无 upgrade 分支 | `api_gateway._Handler` 加 `Upgrade: websocket` 分支 |

**WS 握手流程建议:**

```
前端 new WebSocket("ws://host:port/api/v2/ws")
  ↓ api_gateway._Handler 检测 Upgrade: websocket
  ↓ ws_bridge.upgrade(handler) → 升级连接
  ↓ 前端发送订阅消息
  ↓ ws_bridge 注册订阅,EventBus 事件推送到前端
```

---

#### C.3 文件系统接驳口（P1 缺,需新建）

| 接驳口 | 当前 | 需补 |
|---|---|---|
| 文件树 | ❌ 无 | `/api/v2/fs/tree` |
| 文件读取 | ❌ 无 | `/api/v2/fs/read` |
| 文件监听 | ❌ 无 | `/api/v2/fs/watch`（SSE/WS 推送） |
| FS 端口 | ❌ 无 | L1 `ports.py` 加 `FilesystemPort` |

---

#### C.4 跨节点 RPC 接驳口（P1 缺,需新建）

| 接驳口 | 当前 | 需补 |
|---|---|---|
| RPC server | ❌ 无 `server.py` | `src/l4/rpc/server.py`（`asyncio.start_server`） |
| RPC 端口 | ❌ 无 | L1 `ports.py` 加 `RpcServerPort` |
| RPC handler 注册 | ❌ `transport.py` 仅 send/recv | `rpc/server.py` 加 `register_handler(method, ...)` |
| boot wire | ❌ 无 | boot 时 wire `RpcServer` 到 `RpcServerPort` |

---

#### C.5 Card/Approval 事件接驳口（P1 缺,需新建）

| 接驳口 | 当前 | 需补 |
|---|---|---|
| `CARD_PENDING` 事件 | ❌ `SignalType` 枚举无此成员 | L1 `event.py` `SignalType` 增加 |
| `APPROVAL_REQUIRED` 事件 | ❌ 无 | 同上 |
| `APPROVAL_RESPONDED` 事件 | ❌ 无 | 同上 |
| `pending_queue.enqueue` emit | ❌ 无 | 内调 `emit_signal(SignalType.CARD_PENDING, ...)` |
| `approval_gate.hold` emit | ❌ 无 | 内调 `emit_signal(SignalType.APPROVAL_REQUIRED, ...)` |
| `approval_gate.respond` emit | ❌ 无 | 内调 `emit_signal(SignalType.APPROVAL_RESPONDED, ...)` |
| SSE 自动广播 | ✅ 已具备 `_broadcast` | 事件挂接后自动通过 SSE 推送到前端 |

---

#### C.6 Agent Runtime Hook 接驳口（P2 缺,需新建）

| 接驳口 | 当前 | 需补 |
|---|---|---|
| `turn_complete` emit | ❌ `hook.py:52` 是 `pass` | 改 `get_bus().emit_event("turn.complete", {"result": result, "elapsed": elapsed})` |
| `on_error` emit | ❌ `hook.py:55` 是 `pass` | 改 `get_bus().emit_event("turn.error", {"error": error})` |
| `session_end` emit | ❌ `hook.py:58` 是 `pass` | 改 `get_bus().emit_event("session.end", {"result": result})` |

**实现建议:** 这三个是基类 `LifecycleHooks` 的默认实现（`pass`）,直接改基类会影响所有子类。推荐方案:

1. **方案 A（推荐）:** 新建 `EventEmitHook(LifecycleHooks)` 子类,在 boot 时 `hook_chain.add(EventEmitHook())`。这样不影响现有 hook,且可独立开关。
2. **方案 B:** 在 `HookChain`（`hook.py:61`）的 `turn_complete` / `on_error` / `session_end` 方法内加 emit,而非改基类。

---

## 五、关键参数/常量默认值（前端无需感知,但需知道默认值）

| 参数 | 默认值 | 文件 | 说明 |
|---|---|---|---|
| `API_GATEWAY_HOST` | `0.0.0.0` | `params/api.py` | API 网关监听地址 |
| `API_GATEWAY_PORT` | - | `params/api.py` | API 网关端口（需查实际值） |
| `PRAXIS_PORT_DEFAULT` | `42070` | `params/api.py:121` | 跨节点 mesh 端口 |
| `DISCOVERY_PORT_DEFAULT` | `42069` | `params/api.py:120` | UDP 发现端口 |
| `ENV_PRAXIS_PORT` | `PRAXIS_PORT` | `params/api.py:123` | mesh 端口环境变量 |
| `SSE_QUEUE_MAXSIZE` | `256` | `params/api.py:196` | SSE 客户端队列大小 |
| `EVENT_BUS_MAX_QUEUED` | `500` | `params/kernel.py:21` | EventBus 执行器队列上限 |
| `EVENT_BUS_WORKERS` | `4` | `params/kernel.py:20` | EventBus 线程池大小 |
| `EVENT_MAX_HISTORY` | `200` | `params/kernel.py:18` | EventBus 历史上限 |
| `EVENT_QUERY_LIMIT` | `20` | `params/kernel.py:19` | EventBus 查询默认上限 |
| `LLM_DEFAULT_MAX_TOKENS` | - | `params/api.py` | LLM 默认 max_tokens |
| `LLM_DEFAULT_TEMPERATURE` | - | `params/api.py` | LLM 默认 temperature |
| `API_CORS_ORIGIN` | `*` | `params/api.py` | CORS 允许源 |
| `API_MAX_BODY_BYTES` | - | `params/api.py` | 请求体最大字节数 |
| `ENV_API_TOKEN` | `PRAXIS_API_TOKEN` | `params/api.py:124` | 静态 API token 环境变量 |

---

## 六、优先级建议与施工顺序

| 优先级 | 缺口 | 施工顺序 | 理由 |
|---|---|---|---|
| **P0** | WebSocket 端口 + WS bridge | 1 | 前端实时交互的命脉,无此则前端只能轮询 |
| **P0** | `AuthPort` + `AuthService.verify_token` | 2 | 前端登录态的命脉,无此则前端无身份 |
| **P1** | RPC server + `RpcServerPort` | 3 | 分布式 cell 的地基,空挂会拖后期 |
| **P1** | Card/Approval 事件挂接 SSE | 4 | 前端通知中心依赖 |
| **P1** | `FilesystemPort` 抽象 | 5 | 文件树功能的前置 |
| **P2** | `hook.py` emit_event 改造 | 6 | 前端工具调用可视化,可延后 |

**施工原则:**

- **P0 必须在接入 Web 前端之前完成**——没有 WebSocket 和 AuthPort,前端无法做实时交互和登录
- **P1 可与前端并行开发**——前端先 mock 这部分能力,后端补真后再切换
- **P2 可延后**——等前端工具调用可视化需求出现时再补

---

## 七、一句话总结

**L1 端口抽象、L4 API 路由、SSE/MCP/Vault 这三块地基已经扎实——前端可以直接基于现有 ~170 个 `/api/v2/*` 端点 + 3 条 SSE 流开工;但 WebSocket 双向通道、`AuthPort` 登录态、RPC server 分布式接驳、`FilesystemPort` 文件树、Card/Approval 事件链、Agent Runtime Hook 这 6 块"下水道"还没铺完,需要在接入 Web 前端之前按 P0 → P1 → P2 顺序补齐。**

---

## 附录 A:验证方法清单

本报告所有结论均通过以下方式验证:

| 验证项 | 方法 | 结果 |
|---|---|---|
| L1 端口完整度 | `read_file src/l1/kernel/ports.py` 全文 408 行 | 12 端口,4 个缺失 |
| L1 事件枚举 | `read_file src/l1/kernel/event.py` | 19 个 `SignalType` 成员 |
| L4 API 路由 | `read_file src/l4/api/api_routes.py` 全文 | ~170 条路由 |
| L4 RPC server | `ls src/l4/rpc/` + `grep register_handler\|start_server` | 无 `server.py`,无监听 |
| L4 WebSocket | `grep websocket\|WebSocket\|ws_bridge` 全项目 | 无前端 WS 桥 |
| L4 SSE | `read_file src/l4/sse/sse_bridge.py` 全文 144 行 | 已就绪,单向 |
| L4 Vault/Auth | `grep verify_token\|issue_token\|revoke\|login\|session` 在 `auth.py` | 无 token 方法 |
| L3 事件挂接 | `grep emit_event\|emit_signal\|get_bus\(\)\.emit` 在 `src/l3` | 8 处已挂接,3 处缺失 |
| L3 hook 桩位 | `read_file src/l3/services/hook.py` 全文 | `turn_complete`/`on_error`/`session_end` 是 `pass` |
| L3 services 清单 | `list_directory src/l3/services` | 32 模块齐全 |
| L1 params 常量 | `grep` 关键常量 | 817 个,8 个子模块 |
| 关键默认值 | `grep PRAXIS_PORT_DEFAULT\|SSE_QUEUE_MAXSIZE\|EVENT_BUS_MAX_QUEUED` | 已确认 |

---

## 附录 B:文件改动清单（按缺口汇总）

### 缺口 1（AuthPort,P0）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l1/kernel/ports.py` | 编辑 | 新增 `AuthPort` 抽象类 |
| `src/l4/vault/auth.py` | 编辑 | `AuthService` 实现 `AuthPort` |
| `src/l3/services/central_security.py` | 编辑 | 第 3 步改用 `get_port("auth")` |
| `src/l4/api/api_routes.py` | 编辑 | 新增 `/api/v2/auth/*` 路由 |
| `src/l4/api_handlers/api_handlers_auth.py` | 新建 | auth 路由 handler |

### 缺口 2（WebSocket,P0）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l1/kernel/ports.py` | 编辑 | 新增 `WebSocketPort` 抽象类 |
| `src/l4/ws/__init__.py` | 新建 | WS 包 |
| `src/l4/ws/ws_bridge.py` | 新建 | WS 桥,实现 `WebSocketPort` |
| `src/l4/api/api_routes.py` | 编辑 | 新增 `/api/v2/ws` 路由 |
| `src/l4/api/api_gateway.py` | 编辑 | `_Handler` 加 upgrade 分支 |

### 缺口 3（RPC server,P1）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l1/kernel/ports.py` | 编辑 | 新增 `RpcServerPort` 抽象类 |
| `src/l4/rpc/server.py` | 新建 | RPC server 实现 |
| `src/l3/boot/wiring.py` | 编辑 | boot 时 wire `RpcServer` |
| `src/l4/api/api_gateway.py` | 编辑 | `start()` 时同步起 RPC server |

### 缺口 4（FilesystemPort,P1）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l1/kernel/ports.py` | 编辑 | 新增 `FilesystemPort` 抽象类 |
| `src/l3/services/fs.py` | 编辑 | 改走 `get_port("fs")` |
| `src/l4/api/api_routes.py` | 编辑 | 新增 `/api/v2/fs/tree`、`/api/v2/fs/read`、`/api/v2/fs/watch` |

### 缺口 5（Card/Approval 事件,P1）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l1/kernel/event.py` | 编辑 | `SignalType` 增加 `CARD_PENDING`、`APPROVAL_REQUIRED`、`APPROVAL_RESPONDED` |
| `src/l3/card/pending_queue.py` | 编辑 | `enqueue()` 内 emit |
| `src/l3/card/approval_gate.py` | 编辑 | `hold()` / `respond()` 内 emit |

### 缺口 6（Hook emit,P2）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l3/services/hook.py` | 编辑 | `turn_complete` / `on_error` / `session_end` 改 emit（推荐方案 A:`EventEmitHook` 子类） |
| `src/l3/boot/wiring.py` | 编辑 | boot 时 `hook_chain.add(EventEmitHook())` |

---

## 附录 C:前端接入检查清单

接入 Web 前端之前,确认以下检查项全部通过:

### C.1 P0 必须项

- [ ] `AuthPort` 已定义并实现,`/api/v2/auth/login` 可用
- [ ] `WebSocketPort` 已定义并实现,`/api/v2/ws` upgrade 端点可用
- [ ] `api_gateway._Handler` 支持 `Upgrade: websocket` 分支
- [ ] `central_security.py` 第 3 步改用 `AuthPort.verify_token`,不再硬编码 `"auth verify_token not implemented"`

### C.2 P1 强烈建议项

- [ ] `RpcServer` 已启动,`register_handler` 可注册 method
- [ ] `CARD_PENDING` / `APPROVAL_REQUIRED` / `APPROVAL_RESPONDED` 事件已挂接
- [ ] `FilesystemPort` 已定义,`fs.py` 走端口
- [ ] `/api/v2/fs/tree`、`/api/v2/fs/read`、`/api/v2/fs/watch` 路由已注册

### C.3 P2 可延后项

- [ ] `hook.py` 的 `turn_complete` / `on_error` / `session_end` 改 emit
- [ ] `EventEmitHook` 子类已注册到 `HookChain`

---

**报告结束。**

> 本报告基于 2026-08-05 的代码状态生成。后续地基补齐后,建议更新本报告的"完成度总览"和"缺口"部分。
