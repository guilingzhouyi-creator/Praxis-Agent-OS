---
全宗: DESIGN
案卷: architecture
件号: 001
类型: 设计
日期: 2026-07-22
时间戳: 2026-07-22T19:00
作者: L3
关键词: [NOMOS, Praxis, architecture, Agent OS]
关联: [ARCHIVE-design-002, ARCHIVE-design-003, ARCHIVE-design-006]
债务: []
---

# NOMOS Praxis 完整架构

## 核心决策

定义 Praxis 作为 Agent OS 桌面 Shell 的五层架构、核心组件与 MVP 范围。

## 设计规则

1. Praxis 必须是桌面 Shell（首选），Portal 是 Web 调试界面（备选），CLI 是应急通道。
2. 不用气泡，用卡片 — Agent 输出必须是结构化卡片（执行卡/分歧卡/审查卡），不是聊天气泡。
3. 不用对话，用意念 — 输入必须是结构化意图 Task Card，不是自由文本聊天。
4. 不用压缩，用自动淘汰 — Ring 满自动淘汰最旧记录，无手动压缩按钮。
5. L3 必须使用纯 Python 规则引擎（~100 行），不得引入 LLM 做路由决策。
6. Task Card 必须包含 intent/domain/card_type/context_refs/tools_hint/priority/agent_id 七个字段。
7. Agent Cell 必须包含 3 个对等 Agent 互审，每 Agent 有独立领地。
8. Scout 必须是只读辅助单元，不可写文件，不可再委派（深度 = 1），超时 5 分钟自动终止，每 Agent 最多 3 个活跃 Scout。
9. Agent 间通信必须通过 MessageBus，Agent 禁止直接与人类交互。

## 规格

- 启动命令: `python run.py --gui`（Praxis 桌面）、`python run.py`（Portal Web）、`python run.py --cli`（CLI）
- TaskCard `@dataclass` 字段: intent (str), domain (str), card_type (str), context_refs (list), tools_hint (list), priority (int, 1-5 默认 3), agent_id (str)
- ToolRing 三环容量: Ring 1=32（G1+G2 直行）, Ring 2.5=8（G1-G4 RequestPool）, Ring 3=16（G1-G5 审批+见证）
- RequestPool 调度权重: 信誉 40%, 优先级 35%, 等待时间 25%
- GateChain G5 决策矩阵: 全部 pass → pass | G3 warn + 信誉 ≥ 0.9 → pass | G3 warn + 0.7~0.9 → report | G3 warn + < 0.7 → block | 任意 block → block
- IPC 消息路径: L3→Agent (TASK_ASSIGN/TASK_CANCEL/REVIEW_RESULT), Agent→L3 (TASK_ACCEPT/TASK_DONE/TASK_ERROR/DISPUTE_RAISE), Agent↔Agent (CROSS_REVIEW_REQ/CROSS_REVIEW_RESP/TERRITORY_QUERY)
- Agent→Human 直接通信: 禁止，所有人类交互必须通过 L3
- 三种输入模式: 自由模式（自然语言→L3 解析）、模板模式（模板库选填）、专家模式（直接编辑 YAML Task Card）
- MVP 5 工具: read_file(0/G1-G2), grep_search(0/G1-G2), replace_string_in_file(1/G1-G4), run_in_terminal(1/G1-G4), read_fingerprint(0/G1-G2)

## 排除

- Electron / Tauri / Qt：被 pywebview 替代（<500ms 启动，<50MB 打包，三平台原生 WebView）
- LLM 做 L3 决策：被纯规则引擎替代（Task Card 已结构化，不需要推理）
- SubAgent 概念：被 Scout 替代（只读、深度=1、无状态残留）
