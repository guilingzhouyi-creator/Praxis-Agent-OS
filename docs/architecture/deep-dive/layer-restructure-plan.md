# 层级重构计划 — Layer Restructure Plan

## 现状问题

L3 (Cell 层) 当前 ~45K 行，占全项目 64%，混装了不应该属于 Cell 的横切服务：

```
L3 Cell (~45K) 实际职责:
  ├── Agent 运行时       agent/, agent_terminal/
  ├── 记忆系统            memory/
  ├── 卡系统              card/
  ├── 会话系统            cell/peers/l3a/
  ├── 讨论/Convention     discussion/
  ├── 消息总线            bus/
  ├── 配置管理            config/          ← 应下沉
  ├── 服务基础设施        services/        ← 应下沉
  ├── 错误总线            error_bus/       ← 应下沉
  └── 工具注册表          tool_system/     ← 应下沉
```

## 目标分层

```
L5  User        cli.py, agent_runtime.py                    ~500 行
                CLI entry, user interaction

L4  Bridge      api/, llm/, sandbox/, mcp_bridge, search/   ~10K 行
                LLM provider abstraction, sandbox, LSP, MCP

L3  Cell        agent/, agent_terminal/, memory/, card/,     ~30K 行
                discussion/, bus/, cell/, l3a/
                Cell 核心: agent runtime, memory, cards, L3A orchestration

L2  Services    services/, config/, error_bus/,               ~10K 行
                tool_system/, _tools/
                横切服务: settings, stats, identity, counter,
                工具框架, config 加载, 错误收集

L1  Kernel      os/, event/, gatechain/, vfs/, ipc/,         ~11K 行
                params/, constitution/, lifecycle/
                内核: 状态机、事件、权限、VFS、IPC、常量

L0  Microkernel process/, allocator/, sync/, swapper/        ~3K 行
                进程表、资源分配器、同步原语、交换器
```

## 移动清单

### Phase 1: L3 → L2 下沉（~10K 行）

| 当前路径 | 目标路径 | 行数 | 依赖风险 |
|---|---|---|---|
| `l3/services/` | `l2/services/` | ~8K | 被 agent_loop、terminal、card 引用，需改 ~70 处 import |
| `l3/config/` | `l2/config/` | ~1.7K | 被 boot、agent_loop、constitution 引用 |
| `l3/error_bus/` | `l2/error_bus/` | ~0.8K | 被 ~50 个文件引用 |
| `l3/tool_system/` | `l2/tool_system/` | ~1.7K | 被 tools/、agent_loop、pipeline 引用 |
| `l3/tools/` | `l2/tools/` | ~1.6K | 工具 handlers，被 agent_loop 引用 |
| `l3/resource_buffer/` | `l2/resource_buffer/` | ~0.4K | 被 cell、tools 引用 |

### Phase 2: L1 → L0 剥离（~3K 行）

| 当前路径 | 目标路径 | 行数 | 说明 |
|---|---|---|---|
| `l1/kernel/process.py` | `l0/process.py` | 纯进程表管理 | |
| `l1/kernel/allocator.py` | `l0/allocator.py` | 资源分配 | |
| `l1/kernel/sync.py` | `l0/sync.py` | mutex/semaphore/barrier | |
| `l1/kernel/swapper.py` | `l0/swapper.py` | 上下文交换 | |

### Phase 3: 测试文件对应移动

测试文件随源文件移动：

```
tests/l3/services/    → tests/l2/services/
tests/l3/config/      → tests/l2/config/
tests/l3/error_bus/   → tests/l2/error_bus/
tests/l3/tools/       → tests/l2/tools/
tests/l3/tool_system/ → tests/l2/tool_system/
tests/l3/resource_buffer/ → tests/l2/resource_buffer/
```

## 关键风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | `l3.services.counter` 被 `agent_loop.py` 内部引用 | L3→L2 后 import 路径变化，必须逐个改 ~70 处 |
| 2 | `_term_handlers.py` 中工具 handler 依赖 `l3.tools.*` | tools 下移后 handler 注册路径需同步更新 |
| 3 | 循环依赖：`l2.services` 可能引回 `l3.agent` | 检查所有 import，切断反向引用 |
| 4 | SettingsCenter 初始化时机（boot 中）| boot 顺序需调整：先 init L2 services，再 init L3 Cell |

## 执行策略

分批进行，每批一个独立 commit：

```
Batch 1: tool_system/ + tools/ → L2     (~3.3K 行, ~30 处 import 改)
Batch 2: config/ + error_bus/ → L2      (~2.5K 行, ~60 处 import 改)
Batch 3: services/ → L2                 (~8K 行, 最大批)
Batch 4: resource_buffer/ → L2          (~0.4K 行)
Batch 5: L0 剥离 (process/allocator)    (~3K 行)
Batch 6: 测试文件移动 + CI 更新
```

每批都单独 `git commit` + `git push`，确保 CI 绿。
