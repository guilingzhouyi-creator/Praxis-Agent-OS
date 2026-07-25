---
全宗: DESIGN
案卷: Praxis-v1
标题: Task Card UX Spec
状态: 待实施
关联: [ARCHIVE-design-004]
---

# Task Card UX Spec — 意图卡创建入口设计

## 核心决策

定义 Task Card 的三层输入模式（自由/模板/专家）、MVP 数据结构与 LLM 解析策略。

## 设计规则

1. 用户创建 Task Card 必须满足学习成本为零、结构化输出、渐进增强、无会话陷阱四项目标。
2. 必须提供三层输入模式：自由模式（单行文本→解析→确认）、模板模式（`#` 触发搜索或按钮打开选择器）、专家模式（直接编辑 YAML）。
3. MVP 阶段禁止使用 LLM 解析意图，必须使用关键词规则 `parse_intent_to_task_card()`。
4. Task Card 创建入口必须替代聊天输入框，不暗示"对话"。
5. P1 后方可加入 LLM 增强解析（调用 DeepSeek API 从自由文本解析 domain/context_refs/tools_hint）。

## 规格

- `TaskCard` MVP 字段: `intent` (必填, 1-2 句), `domain` (可选, L3 自动推断), `context_refs` (可选, 默认 []), `tools_hint` (可选, 默认 []), `priority` (可选, 1-5 默认 3)
- MVP `parse_intent_to_task_card()` 实现: 纯关键词规则 `infer_domain(intent)`，返回 TaskCard(intent=intent, domain=domain, context_refs=[], tools_hint=[], priority=3)
- 模板模式触发: 输入 `#` 触发搜索或点击 `[📋 从模板...]` 按钮
- 模板选择器交互: 搜索框 → 匹配模板列表 → 选中 → 填充字段 → [使用此模板]
- 解析结果预览: 卡片式结构化视图，显示 intent/domain/context_refs，[✓ 确认] / [✗ 重新描述]
- 与非会话前提一致性:
  - 无气泡有卡片 → Task Card 预览 = 卡片式结构化视图，不是聊天气泡
  - 无对话有意图 → 输入是"描述意图"，不是"发送消息"
  - 无压缩有淘汰 → Task Card 提交即归档，不参与上下文窗口

## 排除

- 纯模板选择器（方案 B）：被排除（需维护模板库，用户首次行为是打字不是选模板）
- 纯结构化工单表单（方案 C）：被排除（3+ 字段表单劝退新用户）
- MVP 阶段使用 LLM 解析：被排除（P1 后方可引入）
