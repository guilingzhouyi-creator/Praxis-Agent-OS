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
/l3a model show                     → 有效模型配置
/l3a model set <key> <value>        → 覆盖 L3A 模型
/l3a context sources                → 注册的 ContextSource
```

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
