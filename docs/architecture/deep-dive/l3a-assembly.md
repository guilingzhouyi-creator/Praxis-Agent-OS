# L3A Assembly Mode — 决策路由层

## Architecture

```
用户自然语言
    │
    ▼
L3A.parse()
    │
    ├── 模式一: Assembly（会商模式）
    │     ├── DEFAULT     — 手动审批，卡挂起到 PendingQueue
    │     ├── AUTO_APPROVE — 自动推送 Cell 执行
    │     └── CONFERENCE  — 广播 Convention 多 Agent 协商
    │
    └── 模式二: Direct（直达模式）
          └── /connect → Cell.send_direct_message() → AgentTerminal._handle_direct()
```

## 三种子模式

### DEFAULT（手动审批）

L3A 产出 Card → `CardGate.evaluate()` → 标记 `HOLD` → `PendingQueue` 等待人工审批 → 审批通过后 `CardRegistry.dispatch()` → `Cell.execute_card()`

### AUTO_APPROVE（自动审批）

L3A 产出 Card → `CardGate.evaluate()` → `auto_approve=True` → `CardRegistry.dispatch()` → `Cell.execute_card()` → Peer Agents 执行 → 返回结果

### CONFERENCE（大会模式）

L3A 产出 IssueCard → `ConventionProtocol.start()` → 广播 `CONVENE` 到多 Cell → Per-Cell `AnswerSession`（5 阶段）→ `AnswerAggregator` 跨 Cell 合并 → `converge()` → 收敛摘要注入 Memory Ring 2 + CacheDocument → `to_execution_card()` → 执行

## 路由决策

`_route_to_assembly()` 委托 `CardGate.classify()` 做风险评估:

| CardGate 分类 | AssemblyMode | 行为 |
|---------------|-------------|------|
| SMALL + auto_approve | `AUTO_APPROVE` | 直接推送 Cell 执行 |
| MEDIUM + auto_approve | `AUTO_APPROVE` | 直接推送 Cell 执行 |
| LARGE | `DEFAULT` | 挂起到 PendingQueue 等人审批 |
| DISPUTED | `CONFERENCE` | 启动 Convention 大会协商 |
| 架构卡（`_is_architecture_nature`） | `DEFAULT` | 强制挂起，架构级变更需人工决策 |
| CardGate 不可用 | `AUTO_APPROVE` | 降级到自动审批（fail-open） |

## 数据流

```
                ┌──────────────┐
                │    L3A       │
                │  parse()     │
                └──────┬───────┘
                       │ CardUnified
                       ▼
                ┌──────────────┐
                │ _route_to_   │
                │ assembly()   │ ← CardGate.evaluate()
                └──┬───────┬───┘
                   │       │
          AUTO_APPROVE  DEFAULT/CONFERENCE
                   │       │
                   ▼       ▼
           Cell.execute()  PendingQueue / ConventionProtocol
                   │       │
                   ▼       ▼
               Agent     Memory Ring 2
               Result    (convergence 注入)
```

## 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `CONVERGENCE_BUFFER_SIZE` | 100 | 每 phase 环形缓冲区上限 |
| `CARD_GATE_ARCH_KEYWORDS` | [...] | 架构卡检测关键词 |
| `DIRECT_SESSION_TIMEOUT` | 3600s | Direct 模式超时 |
| `CONVENTION_TIMEOUT` | 600s | 大会单轮超时 |
