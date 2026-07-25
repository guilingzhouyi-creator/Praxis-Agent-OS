---
全宗: DECISION
案卷: Praxis-v1
议题: NOMOS Praxis 技术栈与架构决议
时间戳: 2026-07-21T18:00
L3: NOMOSAgent
状态: 讨论中
关联: [ARCHIVE-decisions-001]
---

# NOMOS Praxis — 技术栈与架构议题

## 核心决策

五项议题全部收敛：GUI=Python webview、内核=纯 Python、领地=按层（A）、L3=纯规则引擎、MVP=4 天 5 工具。

## 设计规则

1. GUI 必须使用 pywebview——唯一满足启动 <500ms、打包 <50MB、三平台、Python 零摩擦的方案。
2. 内核必须保持纯 Python——当前瓶颈是 LLM API 调用（500ms-5s），非计算路径（微秒级），引入 Rust/C++ 得不偿失。
3. 领地必须按层划分（方案 A）——Agent A (routes/params/middleware/auth/i18n)、Agent B (pages/services/visa/cache/config)、Agent C (tests/security/nomos_mcp/memories/scripts)。
4. L3 必须使用纯规则引擎 ~100 行 Python——Task Card 已结构化意图，不需要 LLM 推理。渐进路径：初期硬编码路由表，后续自动从宪法生成。
5. MVP 必须在 4 天内完成——禁止包含多 Agent 审批、多单元、Ring Ω、桌面打包。
6. `config/` 必须归属 Agent B（业务层）——config 的业务耦合在 services/，不在 routes/。
7. pywebview 未适配 Python 3.14 时，必须回退 tkinter + tkhtmlview（不阻塞 P0）。

## 规格

- 启动要求: pywebview 实测 200-300ms，打包 15-25MB，三平台系统 WebView 零额外分发
- 性能瓶颈数据: Ring 淘汰 <1μs, 门禁检查 <1μs, JSON 序列化 ~2μs, SHA-256 ~1.5μs, LLM API 500ms-5s（唯一瓶颈，差 30 万倍）
- `L3RuleEngine.match()`: ~20 行 domain 查表 + intent 关键词匹配，返回 AgentId
- `L3RuleEngine.converge()`: ~15 行优先级合并，冲突时取高信誉 Agent
- MVP 组件估算: 意图卡 0.5 天, L3 0.5 天, 1 Agent+5 工具 1 天, 双环面板 1 天, 活动流卡片 0.5 天, pywebview 集成 0.5 天
- MVP 5 工具: read_file(0, 读文件), grep_search(0, 文本搜索), replace_string_in_file(1, 修改文件), run_in_terminal(1, 执行命令), read_fingerprint(0, 反查工具输出原文)
- P1 候选: 第二 Agent + 审批流优先（证明"多 Agent > 单 Agent"），其次工具环指纹链可视化，P2 记忆回灌提示，P3 桌面打包
- 集成路径（议题 #6）: MVP 阶段 `--gui` 启动 Praxis，无标志启动 Flask 开发；Praxis 通过 `import nomos.rings` 直接导入现有代码，不通过 HTTP
- 领地划分（方案 A）: Agent A (routes/params/middleware/auth/i18n, 以读为主), Agent B (pages/services/visa/cache/config, 读写均衡), Agent C (tests/security/nomos_mcp/memories/scripts, 只读审计+写测试，安全修复可跨越所有领地)
- 跨领地操作预估: ~15-20%（80% 操作在领地内不阻塞）

## 排除

- Rust Tauri：被排除（打包虽小，需 Rust 桥接层，单人维护 Python+Rust 负担重）
- C++ Qt：被排除（启动 ~1s > 500ms，打包 > 50MB，桥接复杂维护成本高）
- Electron：被排除（启动 ~2s > 500ms，打包 > 100MB > 50MB 约束）
- Rust/C++ 重写指纹计算：被排除（1000 次调用总耗时 1.5ms，不到一次 API 调用的 1/200）
- L3 使用小模型/大模型：被排除（结构化意图不需要 NLP 理解，额外引入 200ms-2s API 延迟）
- MVP 估算 6-8 天：被排除（OpenCode 的 4 天估算合理，卡片与双环面板共享样式不分离）
- 领地方案 B（按域）和方案 C（手动）：被排除（方案 A 按层跨领地审批最少）
- `config/` 归属 Agent A：被排除（config 业务耦合在 services/，应归 Agent B）
