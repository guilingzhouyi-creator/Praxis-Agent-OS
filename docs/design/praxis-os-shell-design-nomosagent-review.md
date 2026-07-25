---
全宗: REVIEW
案卷: architecture
件号: 001
类型: 审查
日期: 2026-07-21
时间戳: 2026-07-21T19:00
作者: NOMOSAgent
关键词: [NOMOS, Praxis, OS Shell, review, cross-review]
关联: [ARCHIVE-design-006]
债务: []
---

# 🟢 NOMOSAgent 对 Praxis Agent OS Shell 设计的交叉审查

## 核心决策

审查确认 Agent OS Shell 定位升级和 L3 双阶段模型正确，提出 4 项质询和 4 个议题必须实施前解决。

## 设计规则

1. L3 对话历史必须存储在 Portal SQLite（`nomos_l3_dialogues` 表），回灌时只加载"最近 20 条 + 被 Ring 1 引用的历史条目"，不得与 `memories/sessions/` 重复。
2. `app/praxis/` 下文件名必须体现桥接而非重新实现——`gate_chain.py` → `gate_bridge.py`，`tool_ring.py` → `tool_bridge.py`。
3. G5 三态（pass/report/block）的触发条件必须在 D2 设计任务中明确：pass=领地内操作直接执行，report=跨领地边界执行+通知 L3，block=写生产数据拒绝执行。
4. 窗口必须定义默认尺寸（1280×800）、最小宽度（900px）和 <900px 降级策略（右栏折叠为底部弹出面板）。
5. L3 确认等待必须定义状态机——超时自动取消 / 意图卡锁定 / 确认后方可修改。
6. L3 和 Copilot 角色必须分离：L3 是独立模块（元协调），Copilot 是 Agent 之一，不得合并标注。

## 规格

- L3 对话存储: Portal SQLite 表 `nomos_l3_dialogues`，回灌加载 "最近 20 条 + Ring 1 引用条目"，不与 `memories/sessions/` 重复（session 存档=阶段性摘要，L3 对话=原始交互记录）
- 桥接文件命名: `app/praxis/gate_bridge.py`（桥接 `app/services/gate_chain.py`），`app/praxis/tool_bridge.py`（桥接 `app/services/tool_ring.py`）
- G5 三态触发:
  - 🟢 pass: Agent 在领地内操作
  - 🟡 report: Agent 跨越领地边界（执行 + 通知 L3）
  - 🔴 block: Agent 试图写生产数据（拒绝执行）
- 窗口规格: 默认 1280×800，最小宽度 900px（中栏至少 300px），<900px → 右栏折叠为底部弹出面板
- 角色分离: L3 独立进程/模块，不绑定任何 Agent；Copilot 是 Agent A；🟢 只标注 Copilot
- L3 等待确认状态机: 超时自动取消 / 意图卡锁定 / 确认后方可修改
- MVP 条件统一: 设计稿 9 条 + 路线图 7 条 → 统一为 9 条门禁，追加 G8（UI 一致性）、G9（Agent 面板状态）、共存验证

## 排除

- L3 对话存储在内存或文件系统：被排除（内存 OOM 风险，文件并发写冲突）
- `app/praxis/` 下重新实现 GateChain/ToolRing：被排除（应桥接现有 `app/services/`）
- G5 仅二态（pass/block）：被排除（需要三态 pass/report/block 的 report 中间态）
- 窗口可缩小到 680px 以下无限制：被排除（最小 900px，否则中栏无法显示工具调用卡片）
- L3 与 Copilot 角色合并：被排除（L3 不能既当裁判又当运动员）
