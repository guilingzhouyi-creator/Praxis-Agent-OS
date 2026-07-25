---
全宗: DESIGN
案卷: Praxis-v1
标题: Praxis Agent OS Shell — 完整设计稿
状态: 设计稿 — 待三 Agent 评审
样式基准: NOMOS Portal (黑+红+金) + VS Code 风格菜单栏
关联: [ARCHIVE-design-009, ARCHIVE-design-003, ARCHIVE-design-001]
---

# Praxis Agent OS Shell — 完整设计稿

## 核心决策

定义 Praxis 五区域桌面布局、双模式主视图、L3 Chat 交互模型、Agent 状态栏及 MVP 通过条件。

## 设计规则

1. 窗口必须采用五区域布局：VS Code 风格菜单栏（顶）、事务区（左~280px）、主视图（中）、L3 Chat（右~320px）、Agent 状态栏（底）。
2. 中间主视图必须支持双模式切换：监控模式（默认，跟踪 Agent 实时修改）和分歧审阅模式。
3. 事务区必须包含待决策议题列表（上半）和分歧上报卡片（下半）。
4. 文件修改必须标记修改类型：M（绿，修改）、A（蓝，新增）、D（红，删除），每个 Agent 对应独立颜色（A=绿#3fb950，B=蓝#58a6ff，C=红#f85149）。
5. L3 Chat 必须实现永不重置的连续对话线程，核心职责为解读意图→产出 Task Card→挂载事务区→人类确认→推送 Agent→反馈执行结果。
6. Agent 执行流必须实时显示在中间视图顶部（Agent 名+工具名+进度条+状态灯+指纹链+门禁状态）。
7. L3 必须根据改动影响范围分级处理：架构级改动（跨领地）→触发审批流，小范围改动（单领地 2-5 文件）→直接执行，单文件改动→自动执行不需确认。
8. `app/praxis/` 下的 `gate_chain.py` 和 `tool_ring.py` 必须改为桥接模式，不得复制现有 `app/services/` 实现。

## 规格

- 事务区卡片字段: 编号、意图摘要、目标 Agent、影响范围（轻度/中度/重度/架构级）、预估步数、展开显示完整 Task Card
- 分歧审阅模式显示: 分歧文件及行号、Agent A vs B 各自主张+理由+领地、[采纳 A]/[采纳 B]/[人工介入]/[标记误报] 按钮
- 按钮决策写入门禁: 采纳 A→G3 允许 A 改动，采纳 B→相反，人工介入→打开落盘区编辑器，标记误报→分歧记入信誉分调整
- 落盘区 Diff 双视图: 上半=Agent 隔离沙箱 Diff（实时，未落盘），下半=已落盘 Diff（可编辑，编辑时文件树联动）
- Agent 单元状态栏显示: Agent 名+状态灯+信誉分+状态（活跃/等待/就绪）+领地路径+单元内规则提示
- 扩展接口: [+ 添加单元] 按钮，添加后底部出现单元标签页（#1/#2/#3...），每个单元独立三 Agent，共享 Ring Ω
- 窗口加载: 开发 `python run.py`（浏览器 DevTools），桌面 `python run.py --gui`（pywebview 原生窗口）
- `app/praxis/` 文件结构: bridge.py/l3_engine.py/gate_bridge.py/tools.py/tool_bridge.py/task_card.py/transaction.py/dispute.py/territory.py + ui/index.html/praxis.css/praxis.js

## 排除

- 菜单栏右侧堆图标：被排除，用户明确要求"没有右侧的其他东西"
- 单栏布局/小于 900px 无降级：被排除（最小窗口 900px，<900px 时右栏折叠为底部弹出面板）
- 默认 pywebview 窗口尺寸 < 1280x800：被排除
- Portal 与 Praxis 共用 GateChain/ToolRing 实现文件（复制而非桥接）：被排除
