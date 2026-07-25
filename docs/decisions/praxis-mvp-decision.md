---
全宗: DECISION
案卷: Praxis-v1
议题: NOMOS Praxis MVP 决议
时间戳: 2026-07-21T18:30
L3: NOMOSAgent
参与: AtomCode, OpenCode, NOMOSAgent
状态: 已收敛
关联: [ARCHIVE-decisions-002, ARCHIVE-design-001]
---

# NOMOS Praxis — MVP 决议

## 核心决策

五项决议收敛：GUI=pywebview，内核=纯 Python，领地=按层（A/B/C），L3=纯规则引擎，MVP=4 天 5 工具。

## 设计规则

1. GUI 必须使用 Python webview（pywebview）——启动 <500ms，打包 <50MB，三平台原生 WebView。
2. 内核必须保持纯 Python——瓶颈在 LLM API（500ms-5s），不在计算（微秒级），禁止引入 Rust/C++。
3. 领地必须按层划分——Agent A（HTTP 层: routes/params/middleware/auth/i18n）、Agent B（业务层: pages/services/visa/cache/config）、Agent C（质量安全层: tests/security/nomos_mcp/memories/scripts）。
4. L3 必须使用纯规则引擎 ~100 行 Python——Task Card 已结构化意图，禁止引入 LLM 做路由。
5. MVP 范围必须限定在 4 天——意图卡 + L3 + 1 Agent + 5 工具 + 双环面板 + pywebview 窗口。
6. 开发期用 `python run.py`（Flask 浏览器调试），生产期用 `python run.py --gui`（Praxis 窗口），不需要维护两套 API。

## 规格

- P0 前置条件: `pip install pywebview` 在 Python 3.14 上通过，否则回退 tkinter
- MVP 5 工具: read_file(0), grep_search(0), replace_string_in_file(1), run_in_terminal(1), read_fingerprint(0)
- MVP 不需要: 多 Agent 审批、多单元、Ring Ω、桌面打包
- MVP 后 P1 排序: (1) 验证 1 Agent 完成真实任务 (2) 第二 Agent + 跨领地审批 (3) 桌面打包
- Praxis 集成路径（议题 #6, 方案 C）: MVP 阶段 Praxis 独立运行，通过 `import nomos` 直接导入现有代码，不通过 HTTP
- P0 前置: `pip install pywebview` 在 Python 3.14 上验证
- P1 候选: 验证 1 Agent 完成真实任务、第二 Agent + 审批流、桌面打包（按此顺序）
- 开发/生产共存: 开发期 `python run.py` → Flask 浏览器调试，生产期 `python run.py --gui` → Praxis 窗口
- 5 工具明确: read_file(0)/grep_search(0)/replace_string_in_file(1)/run_in_terminal(1)/read_fingerprint(0)

## 排除

- Rust Tauri / C++ Qt / Electron：被 pywebview 替代（Rust = 双语言维护，Qt > 50MB 打包，Electron > 100MB 打包且 > 2s 启动）
- Rust/C++ 重写内核部分：被排除（唯一瓶颈是 LLM API，不是计算）
- 领地按域划分（方案 B）或手动声明（方案 C）：被排除（按层方案跨领地审批最少 ~15-20%）
- L3 使用小模型或大模型：被排除（结构化意图不需要 NLP 理解）
