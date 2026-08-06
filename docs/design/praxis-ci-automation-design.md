# Praxis 自动化 CI 审查模块设计 v2（card-triggered CI review + 模块联动）

> **状态**: 设计定稿（未开工）
> **项目版本**: v0.4.1 "Aether"
> **需求**: Agent OS 新增系统托管的自动化 CI 测试模块——每张执行卡（card）完成后自动触发审查
> **v2 变更**: 补充与 12 个既有模块的联动细节（AutoTestGate / 审批 / 审议 / 声誉 / R4 归档 / 技能演化 / R5 图 / 会话 / 通知 / L2 命令 / 安全 / 调度），并明确与 AutoTestGate 的差异化
> **日期**: 2026-08-06

---

## 0. 总览

| 项 | 结论 |
|---|---|
| 模块位置 | `src/l4/ci_review.py` 新增 `CiReviewService`（L4 Bridge 层） |
| 触发方式 | `CardRegistry` 新增**全局完成监听器** `register_completion_listener()`，`complete()` 内回调 |
| 审查执行 | 复用现有 L4 `CIService.run_pipeline()`（后台线程、平台 shell、超时/重试就绪） |
| 门禁范围 | 按卡片变更文件（sandbox per-hunk 归因）定向执行 ruff / mypy / pytest |
| 智能审查 | 可选 LLM reviewer（默认关闭），复用 `l3.agent.review.perform_review()` |
| 报告与事件 | `CardCiReport` 落盘 JSONL + R4 归档 + EventBus `ci.review.*` + MonitorBus `ci.card.review` |
| API / 命令 | `/api/v2/ci/reviews` 只读查询 + L2 Shell `/ci` 命令（仿 `/test_auto` 模式） |
| 配置 | `config/praxis.yaml` 新增 `ci:` 段；默认值进 `kernel/settings.py` DEFAULTS；运行时开关仿 `loop.auto_test` |
| **关键联动** | 与 `AutoTestGate`（L3 编辑后回归）**互补不重叠**；结论可串接审批/审议/声誉/归档/会话/通知（均为可选策略，默认只读旁路） |

**为什么放 L4 而不是 L3**：层导入约束（L3 → L2/L1，L3 **不得** import L4）。既有
`src/l4/ci.py` 的 `CIService` 已实现管线执行（shell 抽象、后台线程、状态机），
L4 可同时 import L3（card_registry / review / monitor_bus / reputation / archive）与 L4（ci.py / notify.py），
是唯一不破坏分层、且能复用全部既有设施的挂载点。

---

## 1. 现状分析

### 1.1 已具备（复用，零重写）

| 设施 | 位置 | 复用点 |
|---|---|---|
| `CIService.run_pipeline(name, steps, agent_id, timeout)` | `src/l4/ci.py` | 步骤执行、状态机、日志截断、后台守护线程 |
| 卡片完成事件 | `src/l3/card/card_registry.py::complete()` | `emit_signal(EVENT_TASK_ASSIGN, data={"event": "completed"})` + `_notify_subscribers()` + TaskBus webhook + ReferenceChannel |
| 卡片完成订阅 API | `card_registry.subscribe(card_id, cb)` | 模式参考（per-card）；本模块需新增**全局**监听器（见 §2.2） |
| 变更文件归因 | sandbox per-hunk（`agent_id`/`tool_name`/`task_id`/`modified_at`） | 门禁定向到卡片实际改动文件 |
| 对等审查 | `src/l3/agent/review.py::perform_review()` | LLM 审查（PASS/NEEDS_CHANGES/REJECT） |
| 监控事件 | `src/l3/bus/monitor_bus.py` | `MonitorEvent` 入环 + JSONL + SSE |
| 事件总线 | `l1.kernel.get_event_bus().emit_event()` | 字符串类型自动注册（`skill_mutated` 惯例） |
| 平台 shell | `l1.kernel.platform.shell_command()` | 不落地 `shell=True`，`ci.py` 已示范 |
| **AutoTestGate** | `src/l3/tool_system/auto_test.py` | 既有"卡后回归"机制——本模块与其差异化互补（见 §3.1） |
| **R4 归档** | `src/l3/tools/_archive.py::_cmd_archive_store(fonds, series, content, tags)` | 报告归档（`fonds="ci"`），全项目统一归档通道 |
| **声誉** | `src/l1/kernel/reputation.py::record_review(agent_id, approved)` | 结论可选影响执行 agent 声誉（`REP_REVIEW_*`） |
| **审批** | `src/l3/card/approval_gate.py::ApprovalGate.request()` | REJECT 可选升级人工/系统审批（`APPROVAL_REQUIRED` 事件） |
| **审议** | `src/l3/card/card_convention.py::_route_to_convention()` | NEEDS_CHANGES 可选路由多 agent 交叉审议 |
| **通知** | `src/l4/notify.py::send_notification()` | REJECT/失败可选推送（webhook/email/slack/sms/log） |
| **技能演化** | `src/l3/memory/r4_skill_feedback.py`（`fonds="skills", series="lean_trace"`） | 门禁失败可选沉淀 lean trace 供 R4Agent 演化技能 |
| **R5 图** | `src/l3/memory/memory_graph.py::add_semantic_edge()` | 图启用时可选记录审查边（默认图关闭 → 降级 no-op） |
| **会话闭环** | `src/l3/cell/peers/l3a/session.py::_on_card_completed()` | 卡片结果已注入会话历史；审查结论追加进 `result` 即可 |
| **安全** | `src/l3/services/central_security.py::check_all()` | 可选对 LLM 审查输出做内容信任校验 |
| **L2 命令模式** | `config/commands.yaml` + `l2_shell/commands/*.py`（`test_auto` 先例） | `/ci` 命令按同一模式注册 |

### 1.2 缺口（本模块补）

1. **无卡片→CI 的自动触发**：CIService 只能手动 `run_pipeline()`；AutoTestGate 仅在"循环结束有未验证编辑"时触发（agent 级、机会式），**不是**每张完成卡的系统级审查。
2. **无卡片级报告**：管线 run 不含 `card_id` 关联，无法按卡追溯审查结果。
3. **无门禁定向**：没有从 sandbox 归因提取变更文件、拼装定向检查命令的逻辑。
4. **无可观测性钩子**：管线完成不发布 EventBus/MonitorBus 事件（前端无法可视化）。
5. **无下游消费**：审查结论无审批/声誉/归档/会话/通知串接（v2 补齐）。

---

## 2. 架构设计

### 2.1 模块结构（`src/l4/ci_review.py`）

```
CiReviewService(BaseService)                  # name="ci_review"，随 ServiceManager 生命周期管理
├─ register_card_trigger()                    # boot 接线：CardRegistry.register_completion_listener(self._on_card_completed)
├─ _on_card_completed(card_id, state, result) # 触发器：去重 → 后台编排（daemon 线程，不阻塞 complete()）
│    ├─ _collect_changes(card_id, result)     # sandbox per-hunk 归因 → 变更文件清单（封顶 CI_REVIEW_MAX_FILES）
│    ├─ _build_steps(changed_files)           # 配置门禁 → pipeline steps（shlex.quote 转义路径）
│    ├─ _run_pipeline(card_id, steps, agent)  # 复用 CIService.run_pipeline()
│    └─ _on_pipeline_done(run_id)             # 完成回调：报告 + 事件 + 归档 + 可选联动（§3.3）
├─ _llm_review(card_id, result, changes)      # 可选：l3.agent.review.perform_review()
├─ _persist_report(report)                    # JSONL 落盘 + R4 归档 + MonitorBus/EventBus
├─ _dispatch_linkages(report)                 # 按 verdict 触发下游策略（审批/审议/声誉/通知/todo）
├─ query(card_id=None, status=None, limit)    # 只读查询（API / L2 命令用）
└─ stats()                                    # 按卡片/门禁/结论聚合
```

数据类：

```python
@dataclass
class CardCiReport:
    """One CI review result bound to a completed card."""
    card_id: str
    run_id: str                 # 关联 CIService PipelineRun
    state: str                  # completed / failed / cancelled
    verdict: str                # PASS / NEEDS_CHANGES / REJECT / SKIPPED
    gates: list[dict]           # [{name, action, cmd, exit_code, status}]
    changed_files: list[str]
    review: dict                # LLM 审查结果（未启用时 {}）
    archive_ref: str            # R4 归档引用（fonds="ci"）
    error: str
    started_at: float
    completed_at: float
```

### 2.2 触发链（改动最小原则）

`CardRegistry.complete()` 现有尾部追加一次全局通知（`_notify_subscribers` 之后）：

```python
# card_registry.py 新增（沿用 subscribe/unsubscribe 既有风格）
_completion_listeners: list[Callable[[str, str, dict], None]]  # 全局级

def register_completion_listener(self, callback) -> None: ...
def unregister_completion_listener(self, callback) -> None: ...

# complete() 内、_notify_subscribers() 之后：
for cb in list(self._completion_listeners):
    try: cb(card_id, record.state.value, result or {"error": error})
    except Exception: logger.warning(...)
```

- **不选**「监听 EVENT_TASK_ASSIGN 信号」：信号是 L1→L3 的 task 分配语义，含 assign/dispatch/complete 多态，CI 侧需额外过滤且事件 payload 不含 result。
- **不选**「按卡 subscribe」：CI 无法预知未来 card_id。
- 全局监听器与现有 `_notify_subscribers`（per-card）并行，互不影响；L3A 会话闭环（`Session._on_card_completed`）不受干扰。

### 2.3 数据流

```
card 完成
  └→ CardRegistry.complete()
       ├─ emit_signal(EVENT_TASK_ASSIGN, ...)        （既有）
       ├─ _notify_subscribers(...)                    （既有，L3A 会话闭环）
       ├─ 新增: _completion_listeners ──→ CiReviewService._on_card_completed
       │    ├─ 去重（card_id+state 缓存，防重复触发）
       │    ├─ _collect_changes: sandbox 按 agent_id 拉 per-hunk 变更 → 文件清单（封顶）
       │    └─ _build_steps: [ruff, mypy, pytest 定向]（按配置裁剪）
       │         └─ CIService.run_pipeline(name=f"card-{card_id}", ...)  → 后台线程
       │              └─ _on_pipeline_done(run_id)
       │                   ├─ 组装 CardCiReport
       │                   ├─ 可选 LLM 审查（ci.review.llm_review=true）
       │                   ├─ _persist_report: JSONL + R4(fonds="ci") + EventBus + MonitorBus
       │                   ├─ _dispatch_linkages: 按 verdict 串接审批/审议/声誉/通知/todo（均可选）
       │                   └─ 结论回写：追加进 card result（会话历史可见）
       └─ task_bus webhook / reference_channel        （既有，不受影响）
```

### 2.4 门禁定向策略

- 变更文件来自 sandbox per-hunk 归因（`agent_id` 取 card result 中的执行 agent，缺失时回退 card 提交者）。
- 门禁默认（可配置）：
  - `ruff check <changed_files>`（python 文件）
  - `mypy <changed_files>`（python 文件）
  - `pytest <相关测试>`：优先匹配 `tests/**/test_<模块>.py`；无匹配则跳过 pytest 门禁（不跑全量）
- **路径安全**：所有变更文件路径经 `shlex.quote` 拼入命令（防特殊字符注入）；命令模板白名单固定于配置（`CI_REVIEW_*_CMD`），不接受 LLM/外部输入。
- 单卡门禁总超时 `CI_REVIEW_TIMEOUT`（300s），单步超时 `CI_SHELL_TIMEOUT`。
- 并发上限 `CI_REVIEW_MAX_CONCURRENT`（2）：超出排队（FIFO 有界队列 `CI_REVIEW_QUEUE_CAP`）。

### 2.5 智能审查（可选，默认关）

`ci.review.llm_review: true` 时，管线通过后调用
`l3.agent.review.perform_review(agent_id, reviewer_id="ci", task=card.intent, result=card.result)`，
得 PASS / NEEDS_CHANGES / REJECT。LLM 失败降级 SKIPPED（旁路原则：永不阻塞卡片完成流程）。

---

## 3. 模块联动（v2 核心章节）

### 3.1 与 AutoTestGate 的关系（关键差异化）

既有 `src/l3/tool_system/auto_test.py`（L3，`off|async` 开关，`/test_auto` 命令）：
循环结束发现**未验证编辑** → 后台跑**全量**测试套件 → 结果入 Cell L2 缓存
（`AUTO_TEST_CACHE_KEY="auto_test"`）→ 发 `auto_test.result` 事件 → 反馈队列
（`push_feedback`）注入**下一张卡**（最高优先级）。

| 维度 | AutoTestGate（既有） | CiReviewService（本模块） |
|---|---|---|
| 层级 | L3（agent_loop 内） | L4（card_registry 完成时） |
| 触发条件 | 有未验证编辑（机会式） | 每张完成卡（系统性） |
| 测试面 | 全量测试套件 | 变更文件定向（ruff/mypy/相关 pytest） |
| 产物 | L2 缓存 + 下一卡反馈 | 报告 + R4 归档 + API + 事件 |
| 开关 | `loop.auto_test` | `ci.review.enabled` |
| 生命周期 | 跟随 AgentLoop | 跟随 ServiceManager |

**互补关系**：AutoTestGate 回答"这次循环的编辑是否破坏全量基线"（回归雷达）；
CiReviewService 回答"这张卡交付质量如何、可否进入下游"（交付门禁）。两者并存不冲突。

**协调规则**：
1. **不重复跑全量**：CI 门禁默认定向（§2.4），只有无变更文件时才回退到配置内的固定门禁，**永不**主动跑全量（全量回归归 AutoTestGate 管）。
2. **只读消费缓存**：`ci.review.consume_auto_test_cache: true`（默认）时，报告生成前读 Cell L2 `auto_test` 缓存，若该卡所在 Cell 已有最近（TTL 内）回归结果，作为 `report.context.auto_test` 附注（非阻塞，读失败忽略）。
3. **事件不串扰**：`auto_test.result`（L3）与 `ci.review.completed`（L4）独立命名，前端可分别消费。

### 3.2 上游约束（输入侧安全边界）

| 约束源 | 关系 | 设计决策 |
|---|---|---|
| **宪法 Constitution** | 最高权威 | CI 为系统进程（internal 身份），门禁命令白名单来自配置而非 LLM 生成，不逐个过 G1–G5；但模块启停受 `constitution.is_allowed("ci.review", agent_id="system", ...)` 轻量总开关约束（失败降级为不触发，不静默放行） |
| **GateChain** | agent 工具授权 | CI 不占用 agent 工具授权通道；直连 subprocess（`shell_command` 平台抽象），身份声明为系统 |
| **CentralSecurity** | 内容信任 | 可选：LLM 审查输出进报告前过 `central_security.check_all()`（防审查结果携带注入内容）；默认关（LLM 审查本身默认关） |
| **ApprovalGate** | 高危操作审批 | 门禁命令固定白名单 → 无审批面；仅当配置允许"任意命令门禁"（高危模式，默认关）时，执行前 `approval_gate.request("ci.review", ...)` |

### 3.3 下游消费方（输出侧联动，均为可选策略）

| 消费方 | 接口（已验证） | 触发条件 | 携带数据 | 默认 |
|---|---|---|---|---|
| **审批 ApprovalGate** | `ApprovalGate.request(tool_name, agent_id, args, reason)` → 发 `APPROVAL_REQUIRED` | `verdict=REJECT` 且 `ci.review.escalate_reject=true` | `{card_id, verdict, run_id}` | off |
| **审议 Convention** | `CardConventionMixin._route_to_convention(card_id, intent, domain)`（IssueCard + `convene`） | `verdict=NEEDS_CHANGES` 且 `ci.review.route_convention=true` | card 元信息 | off |
| **声誉 Reputation** | `reputation.record_review(agent_id, approved)`（`REP_REVIEW_APPROVED/REJECTED`） | 仅 LLM 审查完成时（机器门禁不刷声誉） | `approved = verdict == PASS` | off |
| **R4 归档** | `_cmd_archive_store(fonds="ci", series="reviews", content=report_json, tags=...)` | 每次报告完成 | `CardCiReport` JSON | on |
| **技能演化** | `fonds="skills", series="lean_trace"`（r4_skill_feedback 模式） | 门禁失败且 `ci.review.lean_trace=true` | 失败摘要（agent, gate, error） | off |
| **R5 图** | `memory_graph.add_semantic_edge(from, to, relation)` | 图启用时（默认关 → 降级 no-op） | card→report `depends_on` | off |
| **L3A 会话** | `Session._on_card_completed(card_id, state, result)`（既有闭环） | 每次完成 | verdict 摘要追加进 `result` | on |
| **通知 Notify** | `send_notification(channel, title, body)`（webhook/email/slack/sms/log） | `verdict∈{REJECT,FAILED}` 且 `ci.review.notify.enabled=true` | 报告摘要 | off |
| **TodoTracker** | `todo_tracker.update(card_id, "verifying"/"escalated")` + `record_attempt` | 门禁失败且 `ci.review.todo_linkage=true` | card_id, gate 名 | off |
| **MonitorBus** | `MonitorEvent(type="ci.card.review", severity, card_id, data)` | 每次完成 | verdict, gates, elapsed | on |
| **EventBus** | `emit_event("ci.review.completed" / "ci.review.failed")` | 每次完成 | card_id, run_id, verdict | on |
| **ReferenceChannel** | `_rc().event("ci.review", {...})` | 每次完成（训练数据管道） | verdict, gates, elapsed | on |

**联动纪律**：所有下游消费一律 **try/except + 非阻塞**（旁路原则，同 Mer/R5）——任一消费方失败不影响报告生成与卡片生命周期；策略开关全部落配置（§5），默认只保留归档/事件/会话回写三条只读链路。

### 3.4 用户面（L2 Shell / CLI / API / 前端）

| 面 | 新增 | 模式参照 |
|---|---|---|
| L2 Shell | `/ci` 命令：`/ci list [status]`、`/ci show <card_id>`、`/ci toggle on|off` | `config/commands.yaml` + `l2_shell/commands/extra.py`（`test_auto` 同款） |
| CLI (main.py) | `python src/main.py ci <card_id>`（可选，非本期必须） | 现有 `ps/status/audit` 子命令 |
| API | `GET /api/v2/ci/reviews`、`GET /api/v2/ci/reviews/{card_id}`、`PUT /api/v2/ci/config` | `loop/auto-test` 端点模式 + `register_endpoint()` |
| 前端 | **零改动**：SSE/WS 已消费 EventBus/MonitorBus 全量事件 | `ci.review.*` / `ci.card.review` 自动可见 |

### 3.5 调度与防爆

- **并发**：CI_REVIEW_MAX_CONCURRENT + 有界队列（防爆原则，同 monitor_bus `_MAX_QUEUED`）。
- **资源隔离**：CI 门禁跑在 L4 后台线程（CIService 既有线程），**不占用** Cell 资源预算 / 推理预算 / agent 声誉配额；不与 L3 scheduler 抢占（文档声明，实现上互不感知）。
- **超时/去重**：单卡总超时 + 单步超时 + `card_id+state` 去重窗口（`CI_REVIEW_DEDUP_TTL`）。
- **重启恢复**：JSONL 报告持久化（`data_dir/ci_reviews.jsonl`），重启后查询不丢；R4 归档为最终真相源。

### 3.6 事件与可观测性（汇总）

| 通道 | 事件 | payload |
|---|---|---|
| EventBus | `ci.review.started` | `{card_id, run_id}` |
| EventBus | `ci.review.completed` | `{card_id, run_id, verdict, gates, elapsed}` |
| EventBus | `ci.review.failed` | `{card_id, run_id, error}` |
| MonitorBus | `ci.card.review`（severity: info/warn/crit） | `{card_id, verdict, gates}` |
| ReferenceChannel | `ci.review` | `{card_id, verdict, gates, elapsed}` |
| JSONL | `data_dir/ci_reviews.jsonl` | 完整 `CardCiReport` |
| R4 | `fonds="ci", series="reviews"` | 完整 `CardCiReport`（最终真相源） |
| （既有，旁路） | `auto_test.result` | AutoTestGate 回归结果（只读消费） |

---

## 4. 文件改动清单（v2）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/l4/ci_review.py` | **新增** | `CiReviewService` 核心（触发/门禁/报告/事件/归档/联动调度，~400 行） |
| `src/l3/card/card_registry.py` | 编辑 | 全局 `_completion_listeners` + `register/unregister_completion_listener()` + `complete()` 尾部触发（~20 行，纯增量） |
| `src/l4/ci.py` | 编辑 | `PipelineRun` 增加 `card_id: str = ""` 字段（报告关联用；向后兼容） |
| `src/l1/kernel/params/system.py` | 编辑 | 新增 `CI_REVIEW_*` 常量（见 §5.1） |
| `src/l1/kernel/settings.py` | 编辑 | `DEFAULTS` 注册 `ci.review.*` 默认值 |
| `config/praxis.yaml` | 编辑 | 新增 `ci:` 段（部署开关 + 联动策略） |
| `src/l3/boot/boot.py` 或 `src/l3/boot/wiring.py` | 编辑 | boot 接线：实例化 + `register_card_trigger()`（wire_from_config 内，随网关启动） |
| `src/l4/api/api_routes.py` | 编辑 | `/api/v2/ci/*` 路由 |
| `src/l4/api/api_endpoints.py` | 编辑 | `register_endpoint()` 注册（kebab-case、参数名=handler 关键字） |
| `src/l4/api/api_handlers_ci.py` | **新增** | handler：查询 + 运行时开关（仿 `loop/auto-test`） |
| `src/l2/l2_shell/commands/extra.py` | 编辑 | `/ci` 命令实现（`test_auto` 同款模式） |
| `config/commands.yaml` | 编辑 | `/ci` 命令定义 |
| `tests/conftest.py` | 编辑 | `_RESETS` 注册 `ci_review.reset_service()` + 全局监听器清理 |
| `tests/l4/test_ci_review.py` | **新增** | 核心 + 联动用例（见 §8） |

> 共享文件纪律：`card_registry.py`、`params/*.py`、`conftest.py`、`config/praxis.yaml` 同一时刻仅一个 writer——
> 开工前先与并行 agent 对齐，必要时拆 `feature/ci-review` 分支独占；`commands.yaml`/`api_endpoints.py` 亦走
> register 通道，不手改分类表。

---

## 5. 配置与常量（v2）

### 5.1 新常量（`src/l1/kernel/params/system.py`，禁止硬编码）

```python
# ── CI review (card-triggered) ──
CI_REVIEW_MAX_CONCURRENT: Final[int] = 2        # 并发审查上限，超出排队
CI_REVIEW_QUEUE_CAP: Final[int] = 64            # 排队有界容量（防爆）
CI_REVIEW_MAX_FILES: Final[int] = 50            # 单卡变更文件封顶（门禁定向用）
CI_REVIEW_TIMEOUT: Final[float] = 300.0         # 单卡门禁总超时
CI_REVIEW_DEDUP_TTL: Final[float] = 3600.0      # card_id+state 去重窗口
CI_REVIEW_PERSIST_FILE: Final[str] = "ci_reviews.jsonl"
CI_REVIEW_ARCHIVE_FONDS: Final[str] = "ci"      # R4 归档 fonds
CI_REVIEW_ARCHIVE_SERIES: Final[str] = "reviews"
CI_REVIEW_AUTOTEST_CACHE_TTL: Final[float] = 300.0  # 消费 AutoTest 缓存窗口
CI_REVIEW_RUFF_CMD: Final[str] = "python -m ruff check {files}"
CI_REVIEW_MYPY_CMD: Final[str] = "python -m mypy {files}"
CI_REVIEW_PYTEST_CMD: Final[str] = "python -m pytest {files} -x -q"
```

### 5.2 默认值（`kernel/settings.py` DEFAULTS）→ praxis.yaml 覆盖

```yaml
ci:
  review:
    enabled: true              # 总开关（false = 完全不触发）
    auto_trigger: true         # 每张完成卡自动审查
    llm_review: false          # 可选 LLM 审查（成本/延迟考量）
    gates: ["ruff", "mypy", "pytest"]   # 门禁子集裁剪
    max_concurrent: 2
    timeout: 300
    consume_auto_test_cache: true        # 只读消费 AutoTest L2 缓存（§3.1）
    lean_trace: false                    # 门禁失败 → R4 skills/lean_trace
    todo_linkage: false                  # 门禁失败 → TodoTracker 记录
    escalate_reject: false               # REJECT → ApprovalGate 升级审批
    route_convention: false              # NEEDS_CHANGES → Convention 交叉审议
    reputation: false                    # 仅 LLM 审查调 record_review
    notify:
      enabled: false
      channel: log                       # log|webhook|email|slack|sms
```

三层配置原则：params 默认 ← discovery（如需）← praxis.yaml，与既有 `prompt.inject.*` / `loop.auto_test` 一致。

---

## 6. API 端点（v2）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v2/ci/reviews?card_id=&status=&limit=` | 查询审查报告列表 |
| `GET` | `/api/v2/ci/reviews/{card_id}` | 单卡最新报告（含 gates/review/verdict/archive_ref） |
| `PUT` | `/api/v2/ci/config` | 运行时开关 `{enabled: bool}`（仿 `PUT /api/v2/loop/auto-test`） |

- `register_endpoint()` 注册（不手改 `API_ROUTES` 分类）；参数名 = handler 关键字参数。
- 本期只读 + 开关；手动重跑/门禁配置修改**不在本期**（后续按需加，走同版本追加或 `/api/v3/`）。

---

## 7. 测试计划（`tests/l4/test_ci_review.py`，v2 含联动用例）

| 用例 | 断言 |
|---|---|
| `test_trigger_on_card_complete` | 注册监听器 → `CardRegistry.complete()` → 生成 run |
| `test_dedup_same_card_state` | 同一 card_id+state 二次完成不重复触发 |
| `test_gates_run_ruff_mypy` | 变更文件→steps 拼装正确（cmd 含 `shlex.quote` 文件清单） |
| `test_report_pass_verdict` / `test_report_failed_verdict` | 全门禁 exit_code=0 → PASS；任一非 0 → NEEDS_CHANGES + error |
| `test_llm_review_optional` | `llm_review=true` 调 `perform_review`（mock）；false 跳过 |
| `test_events_emitted` | EventBus `ci.review.completed` + MonitorBus `ci.card.review` |
| `test_persist_jsonl` | 报告落盘可回读（temp dir） |
| `test_concurrency_cap` | 并发超限排队（不崩溃） |
| `test_card_registry_listener_api` | register/unregister_completion_listener 生命周期 |
| **v2 联动** `test_approval_escalation` | `escalate_reject=true` + REJECT → `ApprovalGate.request` 被调（mock） |
| **v2 联动** `test_convention_route` | `route_convention=true` + NEEDS_CHANGES → `_route_to_convention` 被调（mock） |
| **v2 联动** `test_reputation_llm_only` | 仅 LLM 审查调 `record_review`；机器门禁不调（防刷声誉） |
| **v2 联动** `test_r4_archive_fonds` | 报告 → `_cmd_archive_store(fonds="ci", series="reviews")`（mock） |
| **v2 联动** `test_lean_trace_optional` | `lean_trace=true` 写 `skills/lean_trace`；false 跳过 |
| **v2 联动** `test_autotest_cache_consumed` | 消费 L2 `auto_test` 缓存为附注；**不触发全量门禁** |
| **v2 联动** `test_runtime_toggle` | `PUT /api/v2/ci/config` → enabled=false 后不再触发 |
| **v2 联动** `test_notify_on_reject` | REJECT + notify.enabled → `send_notification` 被调（mock） |
| **v2 联动** `test_path_quoting` | 文件名含空格/`;` 等 → 命令经 `shlex.quote`，无注入 |
| **v2 联动** `test_linkage_failure_nonblocking` | 下游联动抛异常 → 报告仍生成（旁路原则） |

> 测试纪律：门禁命令用 monkeypatch 假执行器（固定 exit_code），真实 `shell_command`
> 路径由既有 `tests/l4/test_ci.py` 覆盖；联动接口全部 mock，不依赖真实子进程长跑。

---

## 8. 验证门

```bash
python -m pytest tests/infra/test_layer_imports.py -x -q   # L4→L3 新导入需 allowlist（如需要）
python -m pytest tests/infra/test_params_compliance.py -x -q
python -m pytest tests/l4/test_ci_review.py tests/l4/test_ci.py -x -q
python -m pytest tests/l2/test_l2_commands.py tests/l2/test_commands_extra.py -x -q   # /ci 命令
python -m l4.api.api_endpoints                              # 端点 manifest 校验
python tests/runner.py                                      # 全量基线
ruff check src/l4/ci_review.py src/l3/card/card_registry.py src/l4/ci.py src/l2/l2_shell/commands/extra.py
```

---

## 9. 风险登记（v2）

| 风险 | 等级 | 缓解 |
|---|---|---|
| 与 AutoTestGate 双重回归/事件串扰 | 高 | 差异化定位（定向门禁 vs 全量回归）；只读消费缓存；事件独立命名 |
| 每卡跑全量 pytest 过慢 | 高 | 门禁定向变更文件/相关测试；无匹配跳过 pytest；超时+并发上限 |
| 下游联动放大故障面 | 中 | 全部 try/except + 非阻塞（旁路原则）；策略开关默认 off（仅归档/事件/会话回写 on） |
| LLM 审查输出携带注入内容 | 中 | 可选 `central_security.check_all()` 校验；LLM 审查默认关 |
| 门禁命令注入（文件路径特殊字符） | 中 | `shlex.quote` 全部路径；命令模板白名单固定于配置 |
| 机器门禁刷声誉 | 低 | `record_review` 仅 LLM 审查路径调用（`ci.review.reputation`） |
| 重复触发（同卡多次 complete） | 低 | `card_id+state` 去重窗口（CI_REVIEW_DEDUP_TTL） |
| Convention 路由 hold 卡阻塞生命周期 | 低 | 复用既有 `_route_to_convention()`（已处理 hold/complete）；仅显式开启时启用 |
| 并发 JSONL/报告写冲突 | 低 | 单例 + RLock；JSONL 追加文件锁（monitor_bus 同款） |
| 与既有 `verify_cadence`/`Verifier` 语义重叠 | 低 | 定位差异：本模块是**卡级、系统托管、可查询报告 + 下游联动**；既有是 agent 循环内编辑后自查 |

---

## 10. 实施顺序（v2）

```
M1 地基：params 常量 + settings DEFAULTS + praxis.yaml ci: 段 + CardRegistry 全局监听器 + conftest reset
    （card_registry 测试先行，独立可合）
M2 核心：ci_review.py（触发/门禁/报告/事件/JSONL/R4 归档）+ 核心单测
M3 联动：审批/审议/声誉/lean trace/通知/todo 策略开关 + 联动单测（§7 v2 用例）
M4 用户面：L2 /ci 命令 + /api/v2/ci/* 端点 + manifest 校验
M5 验证：全量基线 + ruff + 双绿合入（feature/ci-review，--no-ff，保留分支）
```

- M1 无依赖可先行；M2/M3/M4 文件域基本不重叠（core vs 联动 vs api+shell）可部分并行。
- 共享文件（`params/*.py`、`card_registry.py`、`conftest.py`、`praxis.yaml`）仍单 writer，按序落地。
- 分支建议：`feature/ci-review`（可再按 M1/M2/M3 拆子分支），开工前 `git fetch origin && git merge origin/main` 对齐主干。

---

**规划结束（v2）。** 核心复用（CIService 执行器 + card_registry 完成事件 + sandbox 归因 + review 协议 +
R4 归档 + AutoTestGate 差异化）已全部经代码确认，本模块为纯增量接线；12 个下游联动点均为可选策略、
默认只读旁路，无既有设施改造性风险。

---

## 11. 控制面细分（v2.1 补充：功能子开关 + 按面权限）

> 原设计仅暴露 `enabled` 单一总开关（API `PUT /api/v2/ci/config` + L2 `/ci toggle` 共用同一配置键，
> 任一方切换立即影响另一方）。本补充将其细化为**两层颗粒度**：功能子开关独立控制 + 控制面写权限隔离。

### 11.1 功能键白名单（`CI_SETTING_KEYS`）

| 键 | 类型 | 含义 |
|---|---|---|
| `ci.review.enabled` | bool | 总开关（false = 完全不触发审查） |
| `ci.review.auto_trigger` | bool | 每张完成卡自动触发 |
| `ci.review.llm_review` | bool | 可选 LLM 审查 |
| `ci.review.gates` | list[str] | 门禁子集（ruff/mypy/pytest） |
| `ci.review.escalate_reject` | bool | REJECT → ApprovalGate 升级 |
| `ci.review.route_convention` | bool | NEEDS_CHANGES → Convention 审议 |
| `ci.review.reputation` | bool | LLM 审查调 record_review |
| `ci.review.lean_trace` | bool | 门禁失败 → R4 skills/lean_trace |
| `ci.review.todo_linkage` | bool | 门禁失败 → TodoTracker |
| `ci.review.notify.enabled` | bool | 失败通知开关 |

- 白名单常量 `CI_SETTING_KEYS: frozenset[str]` 定义于 `src/l4/ci_review.py`，API/L2 共用。
- **越界键拒绝**：`ci.control.*` 权限键**不在**白名单内——权限本身不可经 API/L2 修改（防自举提权），
  只能通过配置文件（praxis.yaml / SettingsCenter 管理面）调整。

### 11.2 控制面权限模型

| 键（params 常量） | 默认 | 含义 |
|---|---|---|
| `ci.control.api.writable`（`CI_CONTROL_API_WRITABLE`） | `True` | API 面是否有写权限 |
| `ci.control.shell.writable`（`CI_CONTROL_SHELL_WRITABLE`） | `True` | L2 Shell 面是否有写权限 |

- **读永远开放**：`GET /api/v2/ci/config`、`/ci config` 不校验权限。
- **写按面隔离**：API 写前查 `ci.control.api.writable`；L2 写前查 `ci.control.shell.writable`；
  任一面被禁写时仅拒绝写操作（返回 `success: false, error: "writes disabled"`），读不受影响。
- 校验 helper：`CiReviewService._surface_writable(surface: str) -> bool`（默认 true，settings 失败降级放行）。

### 11.3 API 契约（v2.1）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v2/ci/config` | **新增**：返回全部 `ci.review.*` 当前值 + 两面权限状态 |
| `PUT` | `/api/v2/ci/config` | body 直接键值（`{"enabled": false}`）或 `{"key": "...", "value": ...}`；仅白名单键；先查 api.writable |
| `GET` | `/api/v2/ci/reviews` | 不变 |
| `GET` | `/api/v2/ci/reviews/{card_id}` | 不变 |

### 11.4 L2 Shell 契约（v2.1）

| 子命令 | 说明 |
|---|---|
| `/ci config` | 查看全部开关 + 权限状态（读，无权限校验） |
| `/ci set <key> <value>` | 设置单键（白名单 + shell.writable 校验）；value 解析 bool/int/list |
| `/ci toggle` | 保留，等价 `set ci.review.enabled`（仍受 shell.writable 约束） |
| `/ci list` / `/ci show <card_id>` / `/ci` | 不变（读） |

### 11.5 文件改动（增量）

| 文件 | 操作 |
|---|---|
| `src/l1/kernel/params/system.py` | 新增 `CI_CONTROL_API_WRITABLE` / `CI_CONTROL_SHELL_WRITABLE` |
| `src/l1/kernel/settings.py` | DEFAULTS 追加 `ci.control.api.writable` / `ci.control.shell.writable` |
| `config/praxis.yaml` | `ci:` 段追加 `control:` 子段 |
| `src/l4/ci_review.py` | 新增 `CI_SETTING_KEYS` + `_surface_writable()` |
| `src/l4/api_handlers/api_handlers_ci.py` | `handle_ci_config_get` + PUT 支持子键/批量/权限校验 |
| `src/l4/api/api_routes.py` + `api_endpoints.py` | 注册 `GET /api/v2/ci/config` |
| `src/l2/l2_shell/commands/ci.py` | 新增 `config` / `set` 子命令 + 权限校验 |
| `tests/l4/test_ci_review.py` | 新增权限隔离 / 子开关 / GET config 用例 |

### 11.6 测试要点（v2.1）

| 用例 | 断言 |
|---|---|
| `test_api_get_config` | GET 返回全部键 + 两面权限状态 |
| `test_api_put_subkey` | `{"key": "ci.review.llm_review", "value": true}` 生效 |
| `test_api_put_batch` | `{"enabled": false, "auto_trigger": false}` 批量生效 |
| `test_api_put_reject_outside_whitelist` | `{"key": "ci.control.api.writable"}` → 拒绝 |
| `test_api_write_disabled` | `ci.control.api.writable=false` → PUT 拒绝，读仍可用 |
| `test_shell_set` | `/ci set ci.review.llm_review true` 生效 |
| `test_shell_write_disabled` | `ci.control.shell.writable=false` → `/ci set` 拒绝，`/ci config` 仍可用 |
| `test_shell_toggle_respects_permission` | 禁写时 `/ci toggle` 拒绝 |

---

**规划结束（v2.1）。** 控制面细分保持向后兼容（`enabled` 直键形式不变），新增读端点与子键写、
按面权限隔离，权限键本身不可经业务面自举修改。

---

## 12. 作用域细分 + 全量 API 可配置（v3 补充）

> v2.1 提供功能子开关 + 按面写权限，但 `ci.control.*` 权限键被排除在业务面白名单外（防自举提权），
> 且配置粒度仅到全局。v3 目标：**配置按 cell/agent 作用域覆盖**，且**所有项（含权限键）均允许用户
> 通过 API 控制**——权限键需 `admin` 显式确认，兼顾安全与可恢复性。

### 12.1 作用域解析模型（agent > cell > 全局）

| 层级 | 键格式 | 示例 |
|---|---|---|
| 全局默认 | `ci.review.<suffix>` | `ci.review.enabled` |
| Cell 覆盖 | `ci.review.cell.<cell_id>.<suffix>` | `ci.review.cell.cell-sp1.enabled` |
| Agent 覆盖 | `ci.review.agent.<agent_id>.<suffix>` | `ci.review.agent.agent-writer.enabled` |

- `<suffix>` ∈ 10 个功能后缀（`enabled` / `auto_trigger` / `llm_review` / `gates` /
  `escalate_reject` / `route_convention` / `reputation` / `lean_trace` / `todo_linkage` /
  `notify.enabled`）。
- `<cell_id>` / `<agent_id>` 仅允许 `[A-Za-z0-9_-]+`（防设置键注入）。
- **解析优先级**：agent 覆盖存在 → 用之；否则 cell 覆盖存在 → 用之；否则全局默认。
- 判定函数：`CiReviewService._effective(suffix, agent_id="", cell_id="")` —— 内部依次
  `_setting("ci.review.agent.<id>.<suffix>")` → `_setting("ci.review.cell.<id>.<suffix>")`
  → `_setting("ci.review.<suffix>", default)`；中途命中即返回。
- `_on_card_completed` 改为按 `result` 中的 `agent_id` / `cell_id` 解析
  `_effective("enabled", ...)` 与 `_effective("auto_trigger", ...)` 判定是否触发。

### 12.2 白名单与校验（动态 scope 键）

| 函数 | 规则 |
|---|---|
| `CI_SETTING_SUFFIXES: frozenset[str]` | 10 个功能后缀（替代 v2 的完整键集合） |
| `_is_allowed_key(key)` | `ci.review.<suffix>` 或 `ci.review.cell.<id>.<suffix>` 或 `ci.review.agent.<id>.<suffix>`（id 格式校验） |
| `_is_control_key(key)` | `ci.control.*`（权限键，v3 起 API 可写但需 `admin`） |
| `_normalize_key(key)` | 短名（`enabled`）→ `ci.review.enabled`；作用域后缀同样处理 |

- v2 的 `CI_SETTING_KEYS`（完整键 frozenset）升级为 `CI_SETTING_SUFFIXES`（后缀集），
  校验逻辑改为 `_is_allowed_key()` 动态判定——保持向后兼容（旧完整键仍被接受）。

### 12.3 权限键开放（v3 关键变更）

| 项 | v2.1 | v3 |
|---|---|---|
| `ci.control.api.writable` / `ci.control.shell.writable` | 不可经 API/L2 修改 | **API/L2 可写，需 `admin: true` / `--admin` 显式确认** |
| 写入前置检查 | — | `_is_control_key(key)` 时：①必须带 admin 确认；②**跳过** surface writable 门控（防自锁——若 api 被禁写，用户需能恢复） |
| 防误操作 | 完全锁死 | admin 确认字段防无意修改；恢复路径始终可用（admin 可改回） |

- 安全边界说明：admin 确认是**防误操作护栏**而非认证（Praxis 为本地单机 Agent OS，
  操作者即管理员）；若未来需多租户认证，在 `api_gateway` 层加身份校验即可，本模块不重复实现。

### 12.4 API 契约（v3）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v2/ci/config?cell_id=&agent_id=` | 返回全局 `settings`（10 后缀）+ 按作用域解析的 `effective` + `control` 权限状态 |
| `PUT` | `/api/v2/ci/config` | body：`{"key","value"}` / 批量直键 / `{"key","value","scope":{"cell"/"agent"}}` / 权限键 `{"key","value","admin":true}` |

PUT 键展开规则：
- `{"key": "llm_review", "value": true}` → 全局 `ci.review.llm_review`
- `{"key": "enabled", "value": false, "scope": {"cell": "cell-sp1"}}` → `ci.review.cell.cell-sp1.enabled`
- `{"key": "enabled", "value": false, "scope": {"agent": "agent-writer"}}` → `ci.review.agent.agent-writer.enabled`
- `{"key": "ci.control.shell.writable", "value": false, "admin": true}` → 权限键（需 admin，绕过 surface 门控）
- 完整键形式（`ci.review.cell.x.enabled`）仍直接接受；scope 与完整键冲突时以 scope 为准报错。

### 12.5 L2 Shell 契约（v3）

| 子命令 | 说明 |
|---|---|
| `/ci config [--cell <id>] [--agent <id>]` | 查看全局 + 作用域生效值 + 权限状态 |
| `/ci set <key> <value> [--cell <id>] [--agent <id>] [--admin]` | 按作用域设置；`--admin` 用于权限键 |
| `/ci toggle [--cell <id>] [--agent <id>] [--admin]` | 作用域内切换 enabled |

### 12.6 测试要点（v3）

| 用例 | 断言 |
|---|---|
| `test_effective_agent_overrides_cell` | agent 覆盖存在 → 优先于 cell 与全局 |
| `test_effective_cell_overrides_global` | 无 agent 覆盖时 cell 覆盖生效 |
| `test_effective_falls_back_global` | 均无覆盖 → 全局默认 |
| `test_scope_put_cell` | `scope.cell` → `ci.review.cell.<id>.enabled` 写入 |
| `test_scope_put_agent` | `scope.agent` → `ci.review.agent.<id>.enabled` 写入 |
| `test_scope_key_injection_rejected` | cell_id 含 `.` / `;` → 拒绝 |
| `test_control_key_requires_admin` | 权限键无 `admin: true` → 拒绝 |
| `test_control_key_admin_ok` | 带 admin → 写入成功 |
| `test_control_key_skips_surface_gate` | api.writable=false 时 admin 仍可改回（可恢复） |
| `test_trigger_respects_agent_scope` | agent 级 enabled=false → 该 agent 的卡不触发，其他 agent 仍触发 |

---

**规划结束（v3）。** 作用域覆盖（agent > cell > 全局）使 CI 审查可按执行单元精细开关；
权限键经 admin 确认开放给 API/L2（用户全量可控 + 可恢复），无自锁风险。
