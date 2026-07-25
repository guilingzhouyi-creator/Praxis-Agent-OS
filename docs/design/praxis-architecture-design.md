---
全宗: DESIGN
案卷: architecture
件号: 002
类型: 设计
日期: 2026-07-22
时间戳: 2026-07-22T19:00
作者: L3
关键词: [NOMOS, Praxis, architecture, Agent OS, federalism]
关联: [ARCHIVE-design-001]
债务: []
---

# Praxis 完整架构 — Agent OS 联邦制

## 核心决策

定义 Agent OS 联邦制的概念体系、五层架构、L3 双模式、Agent Cell 结构与 Scout 侦察组。

## 设计规则

1. 术语必须精确：人类（最终决策者）、L3 元协调（中央决策层）、Agent Cell（自治联邦）、Peer Agent（平权同侪）、Scout（只读侦察组）、宪法（.nomos-rules.md 最高约束）。
2. 禁止使用 SubAgent、父 Agent、Orchestrator、Worker、spawn——分别用 Scout、委派方、L3 元协调、Peer Agent、委派/路由替代。
3. L3 必须支持两种模式：大会模式（默认，意图→拆解多卡→Agent 认领→收敛）和直达模式（人类指定 Agent→直接分配）。
4. 跨越两种模式的核心约束不可绕过：GateChain G1-G5、交叉审查、审计日志。
5. Agent Cell 内三 Agent 必须平权，无主从关系，各自在领地内自治。
6. 跨领地操作必须经 L3 审批。
7. Scout 必须是只读、无状态、深度=1 的调查单元，不可写文件、不可做决策。
8. 人类必须执行 5 件事：表达意图、确认 Task Card、观察执行、裁决分歧、合并代码。
9. 人类禁止写代码、审查代码、分配任务、追踪依赖、检查安全——这些由 Agent/Scout/L3 完成。

## 规格

- L3 大会模式流程: 人类意图 → NLP 解读 → 拆分为 Task Card → 事务区展示 → 人类确认 → 规则引擎路由 → 执行 → 交叉审查 → 收敛
- L3 直达模式粒度: 最粗（不指定→大会模式）/ 中等（只指定单元→L3 选 Agent）/ 较细（指定单元+Agent→L3 组装卡片）/ 最细（指定全部→跳过侦察和方案）
- Agent Cell 单元: 3 Peer Agent + L3 协调，Agent A (routes/params/middleware/auth/i18n), Agent B (pages/services/visa/cache/config), Agent C (tests/security/nomos_mcp/memories/scripts)
- Scout 属性: 只读、无身份、无领地、深度=1、无信誉、模板池可扩展
- 交叉审查自动流程: 改动落盘隔离区 → 通知其余 Agent → 审查 → 修复 → 重新提交 → 全通过后合并
- 分歧处理: 两 Agent 意见不一致 → 分歧卡上报事务区 → 人类裁决
- L3 边界: 负责解读/拆分/公示/路由/匹配 Agent/收敛/分歧上报/跨单元协调；不替人类决策、不替 Agent 写代码或审查、不替人类裁决分歧、不定义领地边界（宪法定义）
- GateChain G1-G5 严格顺序: G1 领地校验 → G2 权限校验 → G3 参数校验 → G4 信誉校验 → G5 跨单元/生产审批

## 排除

- SubAgent 模型：被 Scout 替代（Scout 只读，不替代执行）
- Orchestrator 集中式调度：被 L3 元协调替代（L3 是决策层，不是编排器）
- 会话式 Chat 设计：L3 Chat 是中央决策层的交互界面，不是聊天气泡（永不重置、分层记忆）
- LLM 裁决分歧：人类必须最终裁决分歧
