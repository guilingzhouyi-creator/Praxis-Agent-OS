# L3A — 会话系统与决策路由

> **Sources:** `src/l3/cell/peers/l3a/` (11 模块包)

## 架构位置

```
L5 CLI
L4 Bridge (LLM, sandbox, API)
  ┌──────────────────────────────────────┐
L3│  L3A (orchestration daemon)          │ ← 独立 daemon，不注册为 Cell agent
  │    ├── SessionManager               │    直接创建 AgentLoop，不走 Cell terminal
  │    ├── L3ASubAgentPool              │    独立线程池，无 Cell 依赖
  │    └── CentralController (L3A+L3B)  │    CardRegistry 卡区统一入口
  │                                      │
  │  Cell (agent runtime)                │ ← L3A 编排 Cell，不居住在其中
  │    ├── agents with terminals         │
  │    ├── CardRegistry                  │
  │    └── memory (Ring 1-4)             │
  └──────────────────────────────────────┘
L2 Shell
L1 Kernel
```

## 模块结构

```
src/l3/cell/peers/l3a/
├── __init__.py    → L3ADaemon 生命周期 + 单例工厂
├── session.py     → Session + SessionHistory + SessionManager
├── subagent.py    → L3ASubAgentPool + spawn/collect/peek 工具 handler
├── context.py     → ContextSource + ContextEpoch + ContextRegistry
├── inbox.py       → PromptInbox (durable admission/promotion)
├── model.py       → L3AModelConfig (prompt > L3A > 全局 > 编译时)
├── archive.py     → R4 archive store / search / transcript restore
├── pipeline.py    → ManagedToolOutput (大结果 spill 文件)
├── task_table.py  → SessionTaskTable (卡任务监视缓存区)
├── helpers.py     → cardwrite_handler, build_l3a_prompt, convergence
├── api.py         → L2 Shell 命令路由
├── types.py       → 共享枚举和 dataclass
└── params.py      → 常量（路径、尺寸等基础设施参数）
```

## Session 生命周期

```
create_session(title)
  ├── Session.create()
  │     ├── uuid4 session_id
  │     ├── ContextEpoch.create(registry)
  │     │     ├── load_all() 所有 ContextSource
  │     │     ├── render_baseline() → 不可变 baseline
  │     │     └── persist() → 磁盘快照
  │     └── PromptInbox.reload() → 恢复未 promote 的输入
  │
  prompt(text)
  ├── limits = _resolve_limits()
  │     l3a.max_steps > 0 ? → loop.max_steps > 0 ? → 999999 (unlimited)
  │     l3a.max_turns > 0 ? → session.max_turns > 0 ? → 0 (unlimited)
  ├── max_turns check
  ├── inbox.admit(text)
  ├── epoch.sync(registry)
  │     ├── load_all() → diff(snapshot) → MidConversationMessage[]
  │     └── update snapshot + persist
  ├── inbox.promote() → user Message
  ├── _report_stats() → StatsCenter + PMU
  ├── AgentLoop.run(model_config, max_steps, timeout)
  │     ├── cardwrite tool → CardRegistry
  │     ├── l3a_spawn tool → L3ASubAgentPool (async)
  │     ├── l3a_collect tool → 阻塞收集
  │     └── l3a_result tool → 非阻塞查询
  ├── turn_count++
  └── return {answer, card_ids, session_id, turn}

close()
  ├── metadata = {session_id, title, turn_count, ...}
  ├── archive.store_session(fonds="AGENT:l3a", series="l3a_session")
  │     └── R4 Archive SQLite (canonical long-term)
  ├── memory.remember(importance=0.7, ring=3)  (fast recall)
  └── snapshot persist
```

## ContextEpoch + ContextSource

```
ContextEpoch (不可变基线 + 变化检测)
  ├── id: str
  ├── baseline: str (完整渲染的 system context)
  ├── snapshot: dict{key: codec.encode(value)}
  ├── turn_count: int
  └── persisted: bool

预注册的 ContextSource:
  memory        → MemoryManager.build_context()
  constitution  → Constitution.summary()
  system_time   → datetime.now(UTC)
  model_info    → L3AModelConfig.show()

sync(): load_all() → diff(snapshot) → MidConversationMessage[] → update snapshot
```

## PromptInbox (durable)

```
admit(text, mode="steer"|"queue") → Admission(id, status="pending")
  steer: 在当前 session drain 中尽快 promote
  queue: 等 session 空闲时 promote

promote() → Admission(status="promoted")
  │ 原子操作：从 inbox 移到 SessionHistory

_persist() → Ring 2 记忆 (tag="l3a_inbox")
reload()  → 启动时恢复 pending admission
```

## L3ASubAgentPool

```
L3ASubAgentPool (全局单例, max_workers=4)
  ├── commission(spec, task, group) → {task_id} (立即返回)
  ├── collect(group, timeout) → [{task_id, spec, status, result}]
  ├── peek(task_id) → {task_id, spec, status, result}
  └── shutdown(wait)

两种规格:
  card-planner:  read_file + grep_search + list_dir + glob + cardwrite
                 输出: {domain, card_nature, phases, tasks, findings}
  investigator:  read_file + grep_search + list_dir + glob (只读)
                 输出: {findings, files_examined, summary}

内部: 每任务创建轻量 AgentLoop，工具从 TOOL_REGISTRY 解析
      卡只有 L3A 能产（通过 cardwrite），子代理也可产卡
      shell/write/edit/test 均禁止
```

### 工具权限

```
                L3A (主)    SubAgent (从)
cardwrite       ✅           ✅
read_file       ✅           ✅
write/edit      ✅           ❌
shell/run       ✅           ❌
test            ✅ (Cell)    ❌
```

### AgentLoop 内使用序列

```
Turn 1: l3a_spawn(spec="card-planner", task="auth 模块分析", group="g1")
        → {task_id: "sa-001"}

Turn 2: l3a_spawn(spec="investigator", task="auth 测试覆盖", group="g1")
        → {task_id: "sa-002"}

Turn 3: l3a_collect(group="g1", timeout=30)
        → [{findings, card_ids}, {findings, files}]

Turn 4: cardwrite(nature="execution", title="auth refactor", phases=[...])
        → {card_id, submitted: true}
```

## L3AModelConfig 继承链

```
prompt(model_config=override)  ← 1. 按 prompt 覆盖
L3A 自身 /l3a model set        ← 2. L3A 配置
praxis.yaml llm:               ← 3. 全局默认
compile-time default           ← 4. params/agent.py

resolve(override) → {provider, model, max_tokens, temperature}
```

## 统计接入

| Metric | 类型 | 目标 |
|---|---|---|
| `l3a.epoch.tokens` | gauge | StatsCenter |
| `l3a.epoch.pressure` | gauge | StatsCenter |
| `l3a.session.turns` | gauge | StatsCenter |
| `l3a.session.tokens_consumed` | counter | StatsCenter |
| `token.estimated` | counter | PMU (CellPmu "l3a") |
| `memory.context.warnings` | counter | PMU (pressure ≥ 0.80) |
| `memory.context.critical` | counter | PMU (pressure ≥ 0.95) |

## L2 Shell 命令

```
/l3a                                → 活跃会话 + 模型
/l3a create [title]                 → 创建会话
/l3a list                           → 活跃 + 归档列表
/l3a info <id>                      → 会话详情 + context stats
/l3a close <id>                     → 关闭 + R4 归档
/l3a messages <id> [limit]          → 消息分页
/l3a tasks <id> [status]            → 卡任务监视表
/l3a todos <id> [update <c> <s>]    → 会话 TODO 表
/l3a model show                     → 有效模型配置
/l3a model set <key> <value>        → 覆盖 L3A 模型
/l3a context sources                → 注册的 ContextSource

/card list|submit|cancel            → 卡区操作
/card approve <id>                  → 审批通过 (HOLD → QUEUED)
/card reject <id> [reason]          → 审批拒绝 (HOLD → CANCELLED)
```

## 会话三张表

L3A 会话维护三个互不冲突的状态结构：

```
SessionHistory        → 对话消息流 + 卡完成注入 (system 消息)
SessionTaskTable      → 卡区执行状态监视 (daemon watcher 对账)
Session TODO 表        → LLM 任务清单 (todowrite 状态机, 会话级隔离)
```

### SessionTaskTable（卡任务监视缓存区）

```
cardwrite → tasks.track(card_id, title, turn)   ← queued 登记
  → Card 执行 (后台)                              ← 不阻塞 prompt
  → 完成回调 → tasks.update(status, result)       ← 即时更新
  → L3ADaemon.tick() → sync_from_registry()      ← 60s 对账补偿
close() → tasks 持久化到 R4 归档 metadata
查询: /l3a tasks <sid> [status] | MCP l3a_tasks
```

### Session TODO 表

每个会话独立持久化 `.praxis/l3a_todos_<sid>.json`（修复了全局共享覆盖 bug）。

```
状态机: pending → in_progress → verifying → verified | escalated | waived
工具:   todowrite (AgentLoop 自动注册, LLM 可用)
别名:   add→pending, completed→verified
查询:   /l3a todos <sid> [update <content> <status>] | MCP l3a_todos
```

### 卡闭环（异步，不阻塞）

```
prompt → cardwrite
  ├── CardRegistry.submit() → QUEUED
  ├── SessionTaskTable.track()
  ├── registry.subscribe(cid, _on_card_completed)
  └── prompt 立即返回
        ↓ (后台)
  Card 执行完成 → _notify_subscribers()
    ├── SessionTaskTable.update(status, result)
    └── history.append("Card <id> → completed: <summary>")
```

## MCP Server 模式

Praxis 可被外部 Agent (OpenCode/Claude Code/Cursor) 通过 MCP 协议驱动。

```
外部 Agent → Authorization: Bearer <PRAXIS_API_TOKEN>
  → GET  /api/mcp/tools/list   → 工具清单 (按模式)
  → POST /api/mcp/tools/call   → 执行工具
  → GET  /api/mcp/ping         → 健康检查
```

三种暴露模式 (`praxis.yaml api.mcp_mode`)：

| 模式 | 工具 | 内容 |
|------|------|------|
| `normal` | ~68 | TOOL_REGISTRY 基础工具 |
| `selected` | 10 | L3A 会话工具 (create/prompt/spawn/collect/tasks/todos...) |
| `full` | ~78 | 基础 + L3A |

## 三种路由模式

| 模式 | 触发条件 | 行为 |
|------|----------|------|
| `AUTO_APPROVE` | CardGate auto_approve | 直接推送 Cell 执行 |
| `DEFAULT` | CardGate size=large/medium | 挂起等待人工审批 |
| `CONFERENCE` | CardGate size=disputed | Convention 多 Agent 协商 |

## 关键配置

```yaml
# config/praxis.yaml
l3a:
  max_steps: 0              # 每轮步数限制 (0=unlimited)
  max_turns: 0              # 会话总轮次 (0=unlimited)
  timeout: 0                # 每轮超时 (0=no timeout)
  idle_timeout: 3600        # 空闲自动关闭
  archive_importance: 0.7   # R4 归档重要性阈值
```

## ASK 澄清工具 (l3a_ask)

当用户提示词歧义或关键信息缺失时，L3A 调用 `l3a_ask` 工具向用户提问
（最多 `ASK_MAX_QUESTIONS` 个，可带选项/必答标记），会话进入 `awaiting`
状态，AgentLoop 检测到 `awaiting_input` 标记提前结束本轮，问题列表返回调用方。

```
prompt(text) → loop → LLM 调 l3a_ask → session 记录问题 → loop break
  → 返回 {ask: [...], status: "awaiting"}
  → 用户回答（三种通道）→ submit_answers → resume_after_ask
  → Q&A 块注入 history → loop 恢复执行
```

回答通道（三通道全支持，聊天框为本质语义）：

| 通道 | 形式 | 行为 |
|------|------|------|
| 聊天框 | 会话内直接输入下一条消息 | `prompt()` 检测 awaiting → 自动作为回答并恢复执行 |
| 命令 | `/l3a ask <sid>` / `/l3a answer <sid> q1=.. q2=.. [自由文本]` | 查询状态 / 填充回答并自动恢复 |
| REST | `POST /api/l3a/ask/status` / `POST /api/l3a/ask/answer` | 前端 UI 使用；answer 体 `{session_id, answers: {q1: ...}, free_form: ...}` |

特性：
- **部分回答**：允许只回答部分问题，未答必答问题在返回的 `missing` 列表中
- **结构化语法**：`q1=windows; q2=python` 精确填充；其余文本进入 free-form
- **持久化**：pending 问题随 session 快照持久化，恢复会话可继续澄清
- **自定义输入**：`free_form` 承载用户非结构化的补充信息，注入 `[User Clarification]` 块
- **常量**：`ASK_MAX_QUESTIONS` / `ASK_MAX_ANSWER_CHARS` / `ASK_STATUS_*`（l3a/params.py）
