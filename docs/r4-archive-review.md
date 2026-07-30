# R4 档案馆体系审查报告

> **审查日期**: 2026-07-30
> **审查范围**: `r4_agent.py`(472行) + `archive_orchestrator.py`(102行) + `_archive.py`(101行)
> **审查标准**: 中国档案馆体系对标 + 全宗理论 + 系统完整性

---

## 1. 体系总览

Praxis R4 档案馆是一个**四级分层记忆架构的持久化层**：

```
MemoryManager                        Archive (SQLite)
  L0 Register ─→ 热数据              ┌─────────────────┐
  L1 Working  ─→ 工作记忆            │  archive 表      │
  L2 ShortTerm─→ 短期记忆            │  id, fonds,      │
  L3 LongTerm ─→ 长期记忆 ──→ R4 ──→│  series, content, │
                                    │  tags, created_at │
                                    │  ttl, updated_at  │
                                    └─────────────────┘
```

**三个核心文件的分工**：

| 文件 | 职责 | 行数 |
|------|------|:----:|
| `r4_agent.py` | 后台守护线程，定时检查 + 技能演化 | 472 |
| `archive_orchestrator.py` | shutdown/boot 时的批量归档与恢复 | 102 |
| `_archive.py` | SQLite 持久化 + 搜索工具 | 101 |

---

## 2. 中国档案馆体系对标分析

### 2.1 全宗理论 (Fonds Theory)

中国档案馆体系的核心概念是**全宗**——一个独立机构或组织形成的全部档案的整体。目前系统的实现：

| 中国标准 | Praxis 实现 | 对标评价 |
|----------|------------|---------|
| **全宗 (Fonds)** | `AGENT:{agent_id}` | ✅ 基本对标——每个 agent 作为一个全宗单位 |
| **案卷 (Series)** | `entry_type`（如 tool_call, skill_evolve） | ✅ 按类型归卷 |
| **件 (Item/File)** | 单条 SQLite 记录 | ✅ 每件一个记录 |
| **全宗号** | `AGENT:` 前缀 | ✅ 有区分前缀 |
| **档号** | 无 | ❌ **缺失**：无 `fonds_code + series_code + item_id` 的层级编码 |
| **全宗名册** | 无 | ❌ 无独立的全宗登记表 |

### 2.2 时间戳体系

| 要求 | 现状 | 评价 |
|------|------|------|
| 每件自动记录创建时间 | `created_at REAL` INSERT 时写入 `time.time()` | ✅ **有** |
| 每件记录更新时间 | `updated_at REAL` | ✅ 有字段但**从不更新**（仅建立时与 created_at 相同） |
| 时间戳格式 | Unix timestamp (float) | ⚠️ 非 ISO 8601，不便人类阅读 |
| 时间戳索引 | `idx_archive_created` | ✅ 有索引 |

**结论**：时间戳机制基本就位，但 `updated_at` 字段从未更新（仅写入时设置一次）。

### 2.3 归档流程

| 中国标准流程 | Praxis 实现 | 评价 |
|------------|------------|------|
| **收集** | Memory Ring 3 → `archive_ring3()` 按重要性阈值筛选 | ✅ |
| **分类** | `_classify()` → agent_id → fonds, entry_type → series | ✅ 自动 |
| **著录** | 无档号、无保管期限、无密级 | ❌ **缺失重要元数据** |
| **入库** | SQLite INSERT | ✅ |
| **检索** | `archive_search()` LIKE 查询 | ⚠️ 仅支持模糊匹配，无高级检索 |

---

## 3. 全宗分配逻辑分析

### 3.1 当前实现

`archive_orchestrator.py` 中的 `_classify()` 函数：

```python
def _classify(entry: dict) -> tuple[str, str]:
    agent = entry.get("agent_id", "unknown") or "unknown"
    etype = entry.get("entry_type", "general") or "general"
    fonds = f"AGENT:{agent}"
    series = etype
    return fonds, series
```

### 3.2 评分

| 维度 | 评分 | 说明 |
|------|:----:|------|
| **自动分配** | ✅ 8/10 | 自动从 entry metadata 提取 agent_id 和 entry_type |
| **降级处理** | ✅ 6/10 | 缺字段时 fallback 到 "unknown"/"general" |
| **层级深度** | ⚠️ 5/10 | 只有 fonds/series 两级，缺少 sub-fonds/sub-series |
| **跨全宗** | ❌ 3/10 | 没有跨全宗的关联机制 |
| **全宗命名规则** | ⚠️ 6/10 | `AGENT:` 前缀好，但硬编码无配置 |

### 3.3 问题

1. **全宗命名无归一化**——`AGENT:agent-a` 和 `AGENT:agent-A` 会被视为两个全宗
2. **全宗数量无上限控制**——每个 agent 自动创建一个全宗，没有全宗名册管理
3. **无全宗生命周期**——agent 被销毁后，其全宗仍留在库中

---

## 4. 分区合理性分析

### 4.1 物理存储

目前使用单文件 SQLite `_ARCHIVE_DB`，所有全宗在**同一个数据库中**：

```
archive 表（单表）
├── fonds = AGENT:agent-a
│   ├── series = tool_call
│   └── series = skill_evolve
├── fonds = AGENT:agent-b
│   ├── series = tool_call
│   └── series = scout
└── fonds = AGENT:agent-c (已销毁)
    └── series = ...
```

### 4.2 评分

| 维度 | 评分 | 说明 |
|------|:----:|------|
| **物理分区** | ❌ 3/10 | 单文件、单表，无物理隔离 |
| **逻辑分区** | ✅ 7/10 | 通过 fonds/series 字段逻辑分区 |
| **索引覆盖** | ✅ 8/10 | 有 `created_at` 和 `fonds_series` 复合索引 |
| **清理机制** | ❌ 2/10 | 无 TTL 自动清理、无全宗删除 |
| **跨全宗查询** | ⚠️ 5/10 | 可以跨 fonds 查询但无权限控制 |
| **WAL 模式** | ✅ 10/10 | 使用 `PRAGMA journal_mode=WAL`，读写不阻塞 |

### 4.3 改进建议

- 单个 SQLite 文件在 10 个 agent × 每年 10 万条记录下仍能承受
- 主要瓶颈是未建立 **保管期限表**，TTL 字段从未被利用进行过期清理
- 建议按年度或全宗分表存储，避免单表过大

---

## 5. R4Agent 双重职责分析

### 5.1 职责一：档案馆检查

R4Agent 的 `tick()` 方法执行以下档案馆任务：

| 检查项 | 方法 | 评分 |
|--------|------|:----:|
| 陈旧的存档条目 | `_detect_stale()` → SQL TTL 检查 | ✅ |
| 增量归档 | `_incremental_archive()` → Ring3 → Archive | ✅ |
| 跨全宗矛盾 | `_check_consistency()` → 同名不同内容 | ✅ |
| 违规告警 | `emit_signal(EVENT_ARCHIVE_ALERT)` → L3A | ✅ |

### 5.2 职责二：技能演化

| 功能 | 方法 | 评分 |
|------|------|:----:|
| 技能进化 | `evolve_skill()` → LLM 生成技能 | ✅ |
| 失败追踪 | `_track_failure()` → lean case 记录 | ✅ |
| 失败处理 | `_process_failure_traces()` → 生成 lean skill | ✅ |
| 技能注入 | `get_lean_cases()` + `get_evolved_skills()` | ✅ |

### 5.3 职责合理性

**两项职责放在一个 Agent 中是合理的**，原因：
1. ✅ 档案馆检查和技能演化都是**后台周期任务**，共享同一个 daemon thread
2. ✅ `_process_failure_traces()` 的 lean case 可以视为"技能档案"——自然衔接
3. ✅ 共享 `_lock` 和 `_running` 生命周期管理

**潜在问题**：
- ⚠️ 技能演化调用 LLM（`evolve_skill()`），可能耗时数秒——这会**阻塞后续的 tick 检查**，因为 `tick()` 是同步调用
- ⚠️ `_process_failure_traces()` 遍历文件系统，如果有大量未处理的 lean case，可能占用大量时间

---

## 6. 完整性检查清单

| 要求 | 状态 | 说明 |
|------|:----:|------|
| **自动时间戳** | ✅ 部分 | `created_at` 自动写入，但 `updated_at` 从不更新 |
| **全宗自动分配** | ✅ | 基于 `agent_id` 自动派生 |
| **全宗合理性** | ⚠️ | 单层 `AGENT:` 命名，无全宗归一化 |
| **分区合理性** | ⚠️ | 逻辑分区 OK，物理分区缺失（单文件） |
| **R4Agent 双职责** | ✅ | 档案馆检查 + 技能演化，共享后台线程合理 |
| **归档正确性检查** | ✅ | `_check_consistency()` 跨全宗矛盾检测 |
| **GateChain 门禁** | ✅ | 通过 Constitution 检查 `archive_ring3` 操作 |
| **身份注册** | ✅ | 在 process table 中注册，通过 G2 身份验证 |
| **降级处理** | ✅ 6/10 | 各种 except 有 logger.warning 兜底 |

---

## 7. 评分与建议

| 维度 | 评分 | 评级 |
|------|:----:|:----:|
| 中国档案馆体系对标 | 6/10 | 🟡 基本对标，缺少档号、保管期限、著录项目 |
| 自动时间戳 | 7/10 | 🟡 有创建时间戳但无更新时间戳 |
| 全宗自动分配 | 7/10 | 🟡 自动但未归一化，无全宗名册 |
| 分区合理性 | 6/10 | 🟡 逻辑分区好、物理分区差、无清理机制 |
| R4Agent 双职责 | 8/10 | 🟢 合理，但 LLM 调用阻塞 tick |
| 代码质量 | 7/10 | 🟡 6 处 `except Exception` 可精确化 |
| **综合** | **6.8/10** | 🟡 功能完整，中国档案馆体系部分对标 |

### 优先修复建议

| 优先级 | 问题 | 估时 |
|--------|------|------|
| P0 | `_archive.py` `_cmd_archive_store()` 中 `updated_at` 未独立更新 | ~2min |
| P1 | 全宗名归一化（大小写敏感导致 `agent-a` ≠ `agent-A`） | ~5min |
| P1 | 添加 `ttl` 过期自动清理（`_detect_stale` 已检查但未删除） | ~5min |
| P2 | `_classify()` 添加档号（`fonds_code + series_code + seq`） | ~10min |
| P2 | `evolve_skill()` 移出 `tick()` 同步路径，改为独立线程 | ~5min |
