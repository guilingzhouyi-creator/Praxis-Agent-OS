# Praxis 负载自适应线程池设计

> **项目版本:** v0.4.2 "Aether"
> **依据:** 2026-08-08 内核地基审计（Rust 迁移前置调研）——平台维度静态绑定已由
> `platform.py` + Ports 装配覆盖；性能策略的剩余价值点在**负载维度**而非平台维度。
> **状态:** 设计阶段（未开工）

---

## 1. 背景与问题

`ThreadPoolWorker`（`src/l1/kernel/worker_thread.py`）是内核唯一的 `WorkerPort`
实现，被事件总线、IPC 传输、子代理池等共享。现有动态扩缩容是**简单启发式**：

| 机制 | 现状 | 缺陷 |
|---|---|---|
| 扩容 | `submit()` 中 `qsize() > workers * 2` 时 +2 | 单阈值、无平滑，突发流量瞬间打满 `MAX`（thundering herd） |
| 缩容 | 仅靠 `idle_timeout`（60s）空闲回收 | 不感知真实负载下降，任务间间歇性空闲导致抖动 |
| 信号 | 仅队列深度 | 未利用完成率、任务耗时、活跃线程等可观测信号 |
| 目标 | 无控制目标 | 无法在吞吐与资源占用之间权衡 |

后果：高并发时段线程池要么过冲（线程数远超有效并行度，锁竞争加剧），
要么反应滞后（队列堆积后才扩容，尾延迟升高）。这正是"动态策略引擎"
唯一有真实价值的位置——但**不是按平台切，而是按负载自适应**。

## 2. 设计目标

1. **平滑**：扩缩容带滞回（hysteresis）+ 冷却时间，避免振荡。
2. **有界**：worker 数始终在 `[MIN, MAX]` 内，队列满时背压（不无限堆积）。
3. **可观测**：控制器状态（目标 worker 数、EWMA 深度、决策历史）可查询、可审计。
4. **可移植**：控制律为纯数值算法，Rust 内核可直接照搬同一套参数与公式。
5. **零侵入**：对调用方无感——仍走 `WorkerPort` 接口。

## 3. 控制架构

```
负载信号（周期采样）                    LoadAdaptiveController（纯算法，无 I/O）
──────────────────────                 ─────────────────────────────────────────
  qsize / capacity  ──► EWMA 平滑 ──► 目标区间 [LOW, HIGH] 判定
  完成率（/s）       ──► 滞回带        ├─ 低于 LOW  → 乘法减容（×0.5，至少 MIN）
  活跃线程数        ──► 冷却计时器     ├─ 高于 HIGH → 加法扩容（+2，至多 MAX）
  任务平均耗时       ──► 输出 target    └─ 区间内    → 维持现状
                                      │
                                      ▼
                          ThreadPoolWorker.grow()/shrink()（现有机制复用）
```

### 3.1 信号定义（采样周期 `LOAD_ADAPTIVE_SAMPLE_INTERVAL = 1.0s`）

| 信号 | 来源 | 用途 |
|---|---|---|
| `queue_ratio` | `queue.qsize() / queue_size` | 主控信号 |
| `completion_rate` | 每秒完成任务数（`_completed` 差分） | 吞吐佐证，防误扩容 |
| `active_ratio` | `_active / len(_workers)` | 并行度利用 |
| `task_elapsed` | 近窗任务平均耗时（EMA） | 慢任务检测 |

### 3.2 控制律

- **EWMA 平滑**：`ewma = α·queue_ratio + (1−α)·ewma_prev`，`α = LOAD_ADAPTIVE_EWMA_ALPHA = 0.3`。
- **目标区间**：`[LOAD_ADAPTIVE_LOW_RATIO = 0.2, LOAD_ADAPTIVE_HIGH_RATIO = 0.6]`（占队列容量比例）。
- **滞回**：连续 `LOAD_ADAPTIVE_HYSTERESIS_SAMPLES = 3` 个采样周期越界才动作，滤掉瞬时毛刺。
- **冷却**：每次决策后进入 `LOAD_ADAPTIVE_COOLDOWN_S = 5.0` 冷却期，期内不重复决策。
- **动作**：
  - `ewma > HIGH` 且冷却结束 → `target = min(MAX, workers + 2)`（加法增，保守）。
  - `ewma < LOW` 且冷却结束 → `target = max(MIN, workers // 2)`（乘法减，快速回收）。
  - 慢任务保护：若 `task_elapsed` 超 `WORKER_POOL_TASK_TIMEOUT` 的 50% 且队列持续满，
    允许一次性扩到 `min(MAX, workers + 4)` 再进冷却（应对 LLM 慢调用）。
- **背压**：队列满时保持现有 FIFO 丢弃语义（`submit()` 已处理），控制器不改变接口契约。

### 3.3 落点

不新增 Port、不破坏 `WorkerPort` 契约——**在 `ThreadPoolWorker` 内部加一个
`LoadAdaptiveController` 协作者**（新模块 `src/l1/kernel/load_adaptive.py`），
由控制器周期采样并调用现有的 `_grow()`/`_try_shrink()` 原语；`submit()` 里的
旧启发式移除，统一走控制器。配置开关：

```yaml
# config/discovery/load_adaptive.yaml（新，三层层配置的中间层）
load_adaptive:
  enabled: true          # false = 退回纯静态池（MIN 固定）
  sample_interval: 1.0
  low_ratio: 0.2
  high_ratio: 0.6
```

## 4. 常量清单（全部进 `src/l1/kernel/params/api.py`，禁止硬编码）

| 常量 | 默认值 | 含义 |
|---|---|---|
| `LOAD_ADAPTIVE_ENABLED` | `True` | 总开关 |
| `LOAD_ADAPTIVE_SAMPLE_INTERVAL` | `1.0` | 采样周期（s） |
| `LOAD_ADAPTIVE_EWMA_ALPHA` | `0.3` | 平滑系数 |
| `LOAD_ADAPTIVE_LOW_RATIO` | `0.2` | 目标区间下界 |
| `LOAD_ADAPTIVE_HIGH_RATIO` | `0.6` | 目标区间上界 |
| `LOAD_ADAPTIVE_HYSTERESIS_SAMPLES` | `3` | 越界确认采样数 |
| `LOAD_ADAPTIVE_COOLDOWN_S` | `5.0` | 决策冷却（s） |
| `LOAD_ADAPTIVE_GROW_STEP` | `2` | 加法扩容步长 |
| `LOAD_ADAPTIVE_SHRINK_FACTOR` | `2` | 乘法减容分母 |
| `LOAD_ADAPTIVE_SLOW_TASK_RATIO` | `0.5` | 慢任务判定阈值（占 TASK_TIMEOUT 比例） |

## 5. 可观测性

- `ThreadPoolWorker.stats()` 扩展：`target_workers`、`ewma_depth`、`last_decision`、
  `decisions_total`、`in_cooldown`。
- 控制器每决策一次 `emit_event("load_adaptive_decision", ...)`（沿用事件总线
  `emit_event`，与 skill 审计同机制）。
- `healthcheck.py` 的模块探针表加入 `load_adaptive` 状态键。

## 6. 与 Rust 迁移衔接

控制器是纯数值算法（EWMA + 区间判定 + 冷却计时），无文件/网络/OS 依赖，
是 FFI 移植的理想候选：

1. `load_adaptive.py` 保持无 I/O——采样数据由调用方传入，控制律纯函数化
   （`decide(metrics) -> Action` 可单测）。
2. Rust 侧 `l1_kernel_rs` 的线程池模块直接复用同一套常量和决策公式，
   参数表（`params/api.py`）与 `praxis.yaml` 作为唯一真源。
3. Python 侧 `ThreadPoolWorker` 可先以 `LOAD_ADAPTIVE_ENABLED` 灰度，Rust
   落地后整体替换，接口不变。

## 7. 测试策略

- **纯函数单测**（`tests/l1/test_load_adaptive.py`）：`decide()` 对构造的
  指标序列（过载/欠载/振荡/慢任务）断言动作正确——不启动线程，毫秒级。
- **集成测试**：`tests/l4/adapters/test_worker_thread.py` 增补——提交批量
  任务模拟过载，断言 `pool_size` 单调增长且不超过 `MAX`；空闲后回落到 `MIN`。
- **回归**：现有 `test_worker_thread.py` 全部用例在 `enabled=true/false`
  两档下通过（开关必须完全透明）。
- **基准**：`bench_card.py` 扩展线程池压测段，记录扩缩次数与吞吐。

## 8. 风险与权衡

| 风险 | 缓解 |
|---|---|
| 采样线程开销 | 单采样线程，1s 周期，决策前先无锁读计数器 |
| 振荡/抖动 | 滞回 3 样本 + 冷却 5s，双保险 |
| 慢任务误判 | 慢任务扩容仅当队列持续满（EWMA > HIGH）才触发 |
| 与静态池行为漂移 | `enabled: false` 完全退回现状，灰度切换 |
| 参数调优盲目 | 常量全部可经 discovery yaml 覆盖，基准脚本对比 |

## 9. 验收标准

1. `ruff check` / `ruff format --check` / `mypy` 通过，层导入测试、params 合规测试通过。
2. 过载压测下 `pool_size` 不超 `MAX`、决策次数有限（冷却生效）。
3. `enabled: false` 下全部现有测试原样通过（零行为变化）。
4. 新常量全部在 `params/api.py`，无硬编码；stats() 暴露控制器状态。

## 10. 附：Agent 工作效率评价组合（后续参考）

> 架构侧总览见 `docs/architecture/cross-cutting.md` 的
> "Agent efficiency evaluation (cross-layer)" 一节。本节的四族指标
> 与第 3 节的负载信号共同构成完整评价体系：**线程池看负载，Agent 看价值**。

单一吞吐（steps/s、ops/s）会被"刷步骤"骗过——反复产出被 Verifier
打回的步骤时 steps/s 很高但价值为零。评价组合四族指标，各回答一个问题：

| 家族 | 回答的问题 | 信号 / 公式 |
|---|---|---|
| **质量加权** | 每秒多少*有效*工作 | 有效吞吐 = 原始吞吐 × Verifier 通过率；返工率 = 被打回步骤 / 总步骤；收敛效率 = 卡片收敛所需步骤（`convergence.py` RESOLVED 占比）；质量-成本比 = 通过步骤 / LLM 调用次数 |
| **延迟分布** | 尾延迟有多糟 | p50/p95/p99 单步耗时（均值只喂吞吐）；Little's Law 交叉校验 `WIP = 吞吐 × 周期`（找并发高但吞吐不涨的临界点）；等待占比 = agent 空闲 / wall（互补第 3 节 active_ratio） |
| **停滞与振荡** | Agent 在空转吗 | 停滞率 = 停滞触发次数 / 总步骤；振荡检测 = EWMA `queue_ratio` 序列过零率 / 方差分析（直接输入第 3 节滞回参数调优）；收敛步数直方图暴露长尾卡 |
| **规模化曲线** | 串行瓶颈在哪 | Amdahl 拟合 `speedup = 1/(1−P + P/N)`（agent 数 1→2→4→8）反推串行占比 P（高 P ⇒ 调度/共享锁瓶颈）；Gustafson 修正（固定墙钟）；饱和拐点 N* = praxis.yaml 并发上限实测依据 |

### 10.1 现有数据源（无需新埋点即可起步）

- 质量：`src/l3/agent/verifier.py`（pass/fail）、`convergence.py`（收敛率）、`stagnation.py`（停滞）。
- 吞吐：`tests/benchmarks/bench_card.py`（wall/steps/s/并行效率/CPU 加速比）、
  `tests/benchmarks/bench_platform.py`（L1 原语微基准，`--json` 跨平台对比）。
- 负载：本设计落地后的 `ThreadPoolWorker.stats()`（`target_workers`/`ewma_depth`/
  `decisions_total`）+ `load_adaptive_decision` 事件流。

### 10.2 落地优先级

1. **质量加权吞吐 + 返工率**——成本最低（Verifier 已有），信息量最大，
   直接扩展 `bench_platform.py --card` 输出；
2. **p95/p99 分位数 + Little's Law**——bench_card 按 step 记录耗时即可，改动小；
3. **Amdahl 缩放曲线**——新增 `bench_scale.py --agents 1,2,4,8`，产出 Rust
   迁移的串行占比基线；
4. **振荡/停滞指标**——待本设计实现后，消费 `load_adaptive_decision` 事件流
   做二次分析，与第 3 节滞回参数形成反馈闭环。

### 10.3 与 Rust 迁移的关系

规模化曲线（10.2.3）是判断"Rust 内核该先优化什么"的主要证据：串行占比 P
高 ⇒ 优先移植/优化调度器与共享锁；P 低 ⇒ 瓶颈在 LLM 调用延迟，Rust 收益有限。
`bench_platform.py` 的跨平台 JSON 报告（Windows/WSL/Linux 各跑一次）为移植
前后提供同一把尺子。

### 10.4 可配置调优因子清单

所有调优因子按三层层配置归属（AGENTS.md）：**编译期默认值进 `params/`，
结构性覆盖进 `config/discovery/*.yaml`，部署级开关进 `config/praxis.yaml`**。
四族评价 + 负载控制律的全部可调点如下：

#### A. 负载控制律（§3，`LOAD_ADAPTIVE_*`，params/api.py）

| 因子 | 默认 | 作用 |
|---|---|---|
| `LOAD_ADAPTIVE_ENABLED` | `True` | 总开关；false 退回静态池（零行为变化） |
| `LOAD_ADAPTIVE_SAMPLE_INTERVAL` | `1.0` | 采样周期（s），越短响应越快、开销越大 |
| `LOAD_ADAPTIVE_EWMA_ALPHA` | `0.3` | 平滑系数；越大越敏感、越易抖 |
| `LOAD_ADAPTIVE_LOW_RATIO` / `HIGH_RATIO` | `0.2` / `0.6` | 目标区间；区间越窄扩缩越频繁 |
| `LOAD_ADAPTIVE_HYSTERESIS_SAMPLES` | `3` | 越界确认样本数；越大越稳、反应越慢 |
| `LOAD_ADAPTIVE_COOLDOWN_S` | `5.0` | 决策冷却；防振荡的主参数 |
| `LOAD_ADAPTIVE_GROW_STEP` | `2` | 加法扩容步长 |
| `LOAD_ADAPTIVE_SHRINK_FACTOR` | `2` | 乘法减容分母 |
| `LOAD_ADAPTIVE_SLOW_TASK_RATIO` | `0.5` | 慢任务判定阈值（占 TASK_TIMEOUT 比例） |

#### B. 质量加权族（新，`EVAL_*`，params/api.py）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_VERIFIER_WEIGHT` | `1.0` | Verifier 通过率在有效吞吐中的权重 |
| `EVAL_REWORK_THRESHOLD` | `0.3` | 返工率告警阈值（>30% 判为刷步骤） |
| `EVAL_CONVERGENCE_WINDOW` | `20` | 收敛步数窗口（steps） |
| `EVAL_COST_WEIGHT` | `1.0` | LLM 调用成本权重（质量-成本比分母） |

#### C. 延迟分布族（新，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_LATENCY_P50/P95/P99` | `—` | 分位数基准线（ms），超线计一次尾延迟 |
| `EVAL_TAIL_PENALTY` | `2.0` | p99 超标时对效率分的惩罚系数 |
| `EVAL_WIP_LIMIT` | `8` | Little's Law 并发上限（praxis.yaml 部署级可调） |

#### D. 停滞/振荡族（新，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_STAGNATION_WINDOW` | `5` | 停滞判定的连续无进展步数 |
| `EVAL_OSCILLATION_ZC` | `4` | 过零率阈值（超之判振荡，回喂 §3 滞回参数） |
| `EVAL_OSCILLATION_VAR` | `0.05` | queue_ratio 方差阈值 |

#### E. 规模化曲线族（新，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_AMDAHL_AGENTS` | `[1,2,4,8]` | 缩放曲线档位（bench_scale.py 用） |
| `EVAL_SERIAL_P_THRESHOLD` | `0.5` | 串行占比 P 判定阈值（>0.5 ⇒ 调度/锁瓶颈） |
| `EVAL_SATURATION_DELTA` | `0.1` | 饱和拐点判定（吞吐增量 <10% 即饱和） |

#### F. 成本/经济维度（新增，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_TOKENS_PER_CARD` | `—` | 单卡总 token（输入/输出分开统计） |
| `EVAL_TOKEN_CACHE_HIT_RATE` | `—` | 缓存命中 token / 总 token（llm.py 已内置 `cache_hit_rate` 字段，零埋点） |
| `EVAL_COST_PER_CARD` | `—` | 单卡金额成本（按 provider 定价 × 用量） |
| `EVAL_CTX_UTILIZATION` | `0.8` | 峰值上下文占用 / 窗口上限告警阈值 |
| `EVAL_TOOL_COST_RATIO` | `—` | 工具调用 token / 思考 token |

#### G. 上下文/记忆维度（新增，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_COMPRESSION_RATIO` | `—` | 会话压缩前后字符比（session_compress.py `compress()`；另有 `pressure_ratio` 触发信号，默认 0.6） |
| `EVAL_MEMORY_RECALL_HIT` | `—` | 记忆检索命中 / 总检索（R4/MemoryGraph） |
| `EVAL_CTX_OVERFLOW_RATE` | `—` | 触发压缩/归档次数 / 会话数（L3A context） |
| `EVAL_ARCHIVE_RESUME_OK` | `—` | 归档会话恢复成功率（`Session.resume_from_archive` 类方法，session.py:126） |

#### H. 信息熵维度（新增，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_STEP_DEDUP_RATE` | `—` | 去重步骤 / 总步骤（复用 loop_detectors SHA256 指纹） |
| `EVAL_INFO_GAIN_RATIO` | `—` | 去重后新信息 token / 总 token |
| `EVAL_ACTION_ENTROPY` | `—` | 相同状态下动作分布熵（过低=机械重复，过高=无目标） |
| `EVAL_USEFUL_FIRST_TIME` | `—` | 首个有效产出耗时 TTFU（与总耗时比=黄金时间利用率） |
| `EVAL_SHARPE_RATIO` | `—` | 类 Sharpe 效率比 = 有效工作 / 步骤延迟标准差（单位波动产出价值；量化思想迁移，比单看吞吐稳健） |

#### I. 可靠性/降级维度（新增，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_STEP_ERROR_RATE` | `0.1` | 失败步骤 / 总步骤告警阈值（分工具类型统计） |
| `EVAL_FALLBACK_RATE` | `—` | 规则降级路径次数 / 总请求（如 _rule_converge 替代 LLM） |
| `EVAL_TOOL_TIMEOUT_RATE` | `—` | 工具超时 / 调用总数（沙箱/网络瓶颈） |
| `EVAL_INTERVENTION_RATE` | `—` | 用户澄清次数 / 卡数（session_ask.py 已有 `turn_count` 计数器；越高=指令质量越差） |

#### J. 调度/系统维度（新增，`EVAL_*`）

| 因子 | 默认 | 作用 |
|---|---|---|
| `EVAL_QUEUE_WAIT` | `—` | RequestPool 排队等待时间分布（scheduler_router.py；当前无时间戳，需在 enqueue/dequeue 加等待时长埋点） |
| `EVAL_BUDGET_USAGE` | `—` | 实际步骤 / ScopeScheduler 预算（scheduler_scope.py） |
| `EVAL_RATE_LIMIT_HIT` | `—` | 速率限制触发次数（scheduler_rate.py） |
| `EVAL_PLAN_ACCURACY` | `—` | 计划步骤数 / 实际步骤数（ExecutionPlan vs 执行，差远=规划失真） |

**引入原则**：凡影响判定边界、权重、窗口、阈值的数字一律走上述因子；
单一数字可被多族共享时（如 `EVAL_WIP_LIMIT` 同时约束调度并发），取更高层
归属（praxis.yaml），避免三处重复定义。新增因子必须注册进
`params/api.py` 并在 `config/discovery/` 建立对应 yaml 映射，否则
params 合规测试（`test_params_compliance.py`）会拦截。**挑选原则**：优先有
现成数据源的因子（每行均已标注来源）；迁移前只跑 A 组 + `EVAL_STEP_DEDUP_RATE`，
生产化后再上记忆/降级组；每组选 1 个主因子做仪表盘主指标（质量组
`EVAL_VERIFIER_WEIGHT × 吞吐`、成本组 `EVAL_TOKENS_PER_CARD`、信息组
`EVAL_SHARPE_RATIO`（替代单看吞吐，稳健性更高）、可靠性组 `EVAL_STEP_ERROR_RATE`），
其余做诊断细节。**因子节制**：40+ 因子须收敛到"4 个主指标 + 诊断细节"的
分层（量化"因子动物园"警告），避免过拟合当前基准。
