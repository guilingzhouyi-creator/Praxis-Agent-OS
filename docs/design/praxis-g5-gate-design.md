---
全宗: DESIGN
案卷: Praxis-v1
标题: G5 门禁定义 + 工具映射审计
状态: 待实施
关联: [ARCHIVE-design-005, ARCHIVE-design-001]
---

# G5 门禁定义与工具映射审计

## 核心决策

定义 G5 上报判定门的触发条件与决策矩阵，审计 PRAXIS_TOOLS 与 NOMOS 实际工具集的映射关系。

## 设计规则

1. G5 触发条件：G1-G4 任一返回非 `pass` 时触发，基于违规严重度 + Agent 信誉 + 最近类似违规频率综合打分。
2. G5 三种输出：`pass`（不上报） / `report`（上报 L3） / `block`（强制阻断）。
3. `app/services/gate_chain.py` 必须新增 `G5 = "gate_5_cross_unit"` 条目。
4. Praxis 必须包装现有工具，不得重新实现（已有工具加 Praxis 包装器，新工具按需新建）。
5. MVP 5 工具必须对应现有 NOMOS 实际工具集，`read_fingerprint` 需新建 Ring 1 查找接口。

## 规格

- G5 判定矩阵：
  - G4 触发 + Agent 信誉 < 0.7 → `block`
  - G3 触发 + 首次 → `report`
  - G3 触发 + 同 Agent 同工具 5 分钟内 > 3 次 → `block`
  - G2 触发 → `block`
  - G1 触发 → `block`
  - 单次违规 + 高信誉 Agent > 0.9 → `pass`（写审计日志但不打断工作流）
- GATES 字典定义位置: `app/services/gate_chain.py`
- MVP 5 工具映射:
  - `read_file(0)`: 调用 VS Code `read_file` (Gate G1+G2)
  - `grep_search(0)`: 调用 VS Code `grep_search` (Gate G1+G2)
  - `replace_string_in_file(1)`: 调用 VS Code `replace_string_in_file` (Gate G1+G2+G3+G4)
  - `run_in_terminal(1)`: 调用 VS Code `run_in_terminal` (Gate G1+G2+G3+G4)
  - `read_fingerprint(0)`: 新建 Ring 1 指纹反查接口 (Gate G1+G2)
- 缺失项必须新建:
  - `app/services/gate_chain.py` 含 G5（不存在需创建）
  - `app/services/tool_ring.py` (Ring 1) MVP 用字典模拟
  - `PRAXIS_TOOLS` 运行时字典（不存在需创建）
  - `authorization.py` 中 danger_level → scopeAllows 桥接层（不存在需创建）

## 排除

- G5 作为保留字段不定义：被排除（多处引用需实施前补完）
- G5 仅 pass/block 二态：被排除（需要三态 pass/report/block）
- `app/praxis/` 下重新实现 GateChain：被排除（只做桥接包装器）
