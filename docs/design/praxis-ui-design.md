---
全宗: DESIGN
案卷: ux
件号: 001
类型: 设计
日期: 2026-07-21
时间戳: 2026-07-21T19:00
作者: NOMOSAgent
关键词: [NOMOS, Praxis, UI, UX, design]
关联: [ARCHIVE-design-008, ARCHIVE-design-001]
债务: []
---

# NOMOS Praxis — 非会话 UI/UX 设计

## 核心决策

否定 Chat UI 的存在前提，建立"无气泡、无对话、无压缩"的卡片化 Agent OS UI 范式。

## 设计规则

1. 无气泡有卡片 — 每次工具调用 = 一张可折叠卡片，禁止使用聊天气泡。
2. 无对话有意图 — 用户发送的是 Task Card（意图 + 上下文引用），不是"消息"。
3. 无压缩有淘汰 — 不显示"上下文窗口 87%"，显示环的实时状态，淘汰在后台自动运行。
4. 不显示百分比上限 — 环没有"满"的概念，只有当前信息密度。
5. 用户只跟 L3 对话 — Agent 领地内自治，跨领地需审批，用户不直接分配任务给 Agent。
6. 工具不按功能分，按危险等级分 — 0 级（纯读）自动通过，1 级（写盘）G1-G4，2-5 级（数据操作）逐级增加审批/见证/快照/确认要求。
7. 模型不需要知道等级 — 模型正常发 tool_call，Praxis 根据危险等级自动路由。

## 规格

- 三栏布局: 意图卡面板（左） | Agent 活动流 + Diff（中） | 双环状态面板（右）
- 四种活动流卡片样式: ToolCallCard（工具名+门禁灯+指纹引用，默认折叠）、ReasoningCard（实时流式，60s 后自动折叠）、KnowledgeCard（Ring 2→R3 提取通知）、回灌提示卡片
- 双环状态面板显示: 共享环用量/私有环用量/层级分布（L2-L7）/淘汰速率/Token 估算——无百分比上限
- 工具环指纹链面板显示: Agent 名、链完整性、最近工具调用、门禁统计（pass/warn/block/report）
- Agent 面板显示: 三 Agent 状态灯（活跃/空闲/未启动）、信誉分、领地、跨领地审批状态、治理层状态（共享环/指纹链/申请池/G1-G5）
- PraxisToolInterceptor 流程: GateChain check → 执行 → 指纹化 → 写入 ToolRing → 压缩摘要至 MemoryRing2 → 返回摘要（非原文）
- 危险等级 0 级工具: read_file, grep_search, list_dir（Gate: G1+G2）
- 危险等级 1 级工具: replace_string_in_file, create_file, run_in_terminal（Gate: G1+G2+G3+G4）
- 危险等级 3-5 级工具: needs_approval=true, 5 级额外 needs_witness=true+needs_snapshot=true, db_migrate+deploy 额外 L3_CONFIRM
- Ring Ω（跨单元治理环）: 容量 100，继承 SharedRing 淘汰策略，新增 unit_reputations 字典、cross_feed/cross_tool_request 接口
- 窗口缩放模型: 单单元模式（意图卡+活动流+单元面板）→ 多单元模式（意图卡+活动流+Ring Ω+多单元折叠卡片）
- 实施优先级: P0（意图卡输入+活动流布局+双环状态面板，2-3天）/ P1（工具调用卡片+LLM 集成，2+天）/ P2（Agent 面板+指纹链可视化）/ P3（记忆回灌提示）

## 排除

- 聊天气泡滚动列表：被 Agent 活动流卡片取代
- "输入框+发送按钮"：被意图卡取代
- "压缩对话"手动按钮：被自动淘汰取代
- 单层三环结构：被分形递归三环取代（Ring Ω 跨单元治理）
- 工具按功能分类：被危险等级分类取代
