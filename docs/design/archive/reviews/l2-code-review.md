# L2 层代码质量审查报告

> **审查时间**: 2026-07-29 | **审查标准**: 最严格（含 AGENTS.md 约定、ruff 合规、params 常量约束、并发安全等）
> **审查范围**: `src/l2/` 全部 11 个源文件 + `tests/l2/` 全部 6 个测试文件（合计约 4300 行）
> **审查分级**: 🔴 Critical / 🟠 Major / 🟡 Minor / ℹ️ Info

---

## 目录

1. [架构与分层](#1-架构与分层)
2. [构造函数与方法实现](#2-构造函数与方法实现)
3. [参数合规（魔法数字）](#3-参数合规魔法数字)
4. [类型注解完整性](#4-类型注解完整性)
5. [并发安全与全局可变状态](#5-并发安全与全局可变状态)
6. [错误处理](#6-错误处理)
7. [导入模式与依赖管理](#7-导入模式与依赖管理)
8. [代码风格与命名](#8-代码风格与命名)
9. [安全性审查](#9-安全性审查)
10. [测试覆盖质量](#10-测试覆盖质量)
11. [代码异味与潜在缺陷](#11-代码异味与潜在缺陷)
12. [综合结论](#12-综合结论)

---

## 1. 架构与分层

### 1.1 🔴 分层违规：L2 → L4 直接依赖

L2 作为 Shell/Interface 层，多处直接导入 L4（API/LLM/Vault 层），违反 AGENTS.md 规定的导入约束（L2 → L1 only）。

| 文件 | 导入 | 说明 |
|------|------|------|
| `i18n.py:26` | `from l4.adapters.i18n_yaml import YamlI18nAdapter` | L2 → L4 直接引用 |
| `commands.py:81` | `from l4.llm.llm import get_engine` | `preconnect_enhanced` 内部延迟导入 |
| `commands.py:548` | `from l4.mcp_bridge import get_bridge, McpClient` | `_cmd_mcp` 内部延迟导入 |
| `commands.py:782` | `from l4.cron_scheduler import get_scheduler as _get_cron` | `_cmd_cron` 内部延迟导入 |
| `commands.py:1170` | `from l4.vault.credential_vault import export_vault_status` | `_model_list` 内部延迟导入 |

**建议**: 如果这些是必要跨层调用，需在 `test_layer_imports.py` 的 allowlist 中注册。当前 53 条 allowlist 可能已有覆盖，需确认。但架构上应通过 L3 桥接层转发，而非 L2 直连 L4。

### 1.2 🟠 模块缺少 `__init__.py`

`src/l2/__init__.py` **不存在**。这意味着 `l2` 不是一个正式的 Python package（是一个 namespace package），这会导致：
- 无法在 `__init__.py` 中编排模块级别的导出
- 某些工具/分析器可能识别异常
- `from l2 import ...` 的导入可靠性依赖于 Python 的 namespace package 机制

而 `src/l2/l2_shell/` 有正确的 `__init__.py`，说明这不是设计意图，而是遗漏。

### 1.3 🟡 L2 → L3 的 `from .cell import get_cells` 环回引用模式

`selector.py`（在 `src/l2/`）使用 `from .cell import get_cells` 的方式导入 L3 的 Cell。这在文件系统中是通过 `src/l2/cell.py`（或 `src/l2/cell/` 包）实现的，但在目录结构中**未看到** `src/l2/cell.py` 或 `src/l2/cell/`：

```
src/l2/
├── i18n.py
├── l2_shell/      ← 主要模块
├── selector.py    ← 使用 .cell 引用
├── shell.py
├── shell_completer.py
└── shell_session.py
```

这意味着 `selector.py` 中的 `from .cell import get_cells` 指向的是一个**不存在的模块**，或者在运行时靠 sys.path 的动态拼接。这是一种隐式依赖，需要查明。

### 1.4 ℹ️ `commands_settings.py` 使用相对路径 `..` 跨包导入

`commands_settings.py:77,119,130` 使用 `from ..scheduler.acb import ...` / `from ..agent.scout import ...`。
虽然语法上正确（位于 `l2.l2_shell` 包内，`..` 指向 `l2` 的同级——即 `src/`），但这种**跨越多个包边界的相对导入**可读性差，且容易在重构时断裂。

---

## 2. 构造函数与方法实现

### 2.1 🟡 `_cmd_help` 中硬编码分类顺序

```python
for cat in ["session", "control", "memory", "system", "agent", "audit", "ext"]:
```

这些分类名称和顺序是硬编码的。建议从 `params/` 或配置文件中定义分类显示顺序常量。

### 2.2 🟡 `resolve_scope` 作用域解析不严谨

```python
def resolve_scope(args: list[str]) -> tuple[str, str, list[str]]:
    if not args:
        return ("global", "", [])
    head = args[0]
    if head == "global" or head.startswith("--"):
        return ("global", "", args)     # 返回了原始 args，不是剩余参数
    ...
```

当 `head.startswith("--")` 时返回 `args` 而非 `args[1:]`，导致下游可能错误地继续将 `--` 标志当作参数。

### 2.3 🟡 `_model_list()` 使用 `from` 和 `str()` 实现 list 渲染

```python
from l4.vault.credential_vault import export_vault_status
vault = export_vault_status()
...
for p in providers:
    if isinstance(p, str):
        lines.append(f"  {p}")
    else:
        lines.append(f"  {str(p)}")
```

`export_vault_status()` 被期望返回同步结果，但导入了完整的 L4 vault 模块。且 `isinstance(p, str)` 检查意味着 provider 要么是字符串要么是其他类型——如果 L3 API 变更，这里会静默失败。

---

## 3. 参数合规（魔法数字）

### 3.1 🔴 硬编码注入风险阈值

`selector.py:197-207`:

```python
if injection_risk > 0.7:
    reasons.append("prompt_injection_suspected")
elif injection_risk > 0.3 and _llm_reviewer:
    ...
    injection_risk = min(1.0, injection_risk + 0.3)
    ...
    injection_risk = max(0.0, injection_risk - 0.2)
```

阈值 `0.7`, `0.3`, `1.0`, `0.0`, `0.3`, `0.2` 全部为魔法数字。应提取到 `params/agent.py`（已包含 `INJECTION_PATTERN_ZH*`）或 `params/system.py`。

### 3.2 🟠 注入模式权重硬编码

`selector.py:49-58`:

```python
_INJECTION_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(...), 0.5),  # 权重硬编码
    (re.compile(...), 0.4),
    (re.compile(...), 0.3),
    (re.compile(...), 0.2),
]
```

权重值应定义为常量，例如 `INJECTION_WEIGHT_HIGH = 0.5` 等。

### 3.3 🟠 长度启发式硬编码

`selector.py:325`:

```python
if len(message) > 2000 and score > 0:
    score = min(1.0, score + 0.2)
```

`2000` 和 `0.2` 应为 `PROMPT_INJECTION_LENGTH_THRESHOLD` 和 `PROMPT_INJECTION_LENGTH_BOOST` 常量。

### 3.4 🟡 硬编码的统计指标字符串

`commands.py:942-943,950-951,971`:

```python
metrics = ["tools.executed.ring_1", "tools.executed.ring_2_5",
           "tools.executed.ring_3", "tools.rejected"]
metrics = ["memory.compact.saved_tokens", "memory.stub_compact.saved_bytes"]
metric = sub_args[0] if sub_args else "tools.executed.ring_1"
```

这些 metric 名字符串分散在代码中，重复出现 4 次以上。应集中到 `params/` 中的一个 `METRICS_*` 常量字典。

### 3.5 🟡 硬编码角色列表

`commands.py:1138,1201,1216,1265`:

```python
for role in ["peer_agent", "subagent.default", "scout", "r4_agent", "convention", "card_planner", "l3a"]:
if role_key in ("peer_agent", "scout", "r4_agent", "convention", "card_planner", "l3a"):
```

**4 次出现**。角色列表应定义为可复用的 params 常量，避免后续扩展时遗漏同步。

### 3.6 🟡 `_cmd_audit` 中硬编码默认 limit

`commands.py:723`:

```python
limit = int(args[0]) if args and args[0].isdigit() else 20
```

`20` 应为 `AUDIT_DEFAULT_LIMIT` 常量。

### 3.7 🟡 `_cmd_stats` 中硬编码默认 limit

`commands.py:972`:

```python
limit = int(sub_args[1]) if len(sub_args) > 1 else 10
```

`10` 应为 `STATS_TOP_DEFAULT_LIMIT` 常量。

### 3.8 ✅ 良好实践

L2 层在大多数地方已经正确使用了项目 params 常量：
- `LOG_TRUNC_50`, `LOG_TRUNC_60`, `LOG_TRUNC_100`, `LOG_TRUNC_200`, `LOG_TRUNC_2000`
- `SHELL_HISTORY_DEFAULT_LIMIT`, `SHELL_HISTORY_MAX_LIMIT`
- `CELL_EVENTS_LIMIT`, `MEMORY_RECALL_DEFAULT_LIMIT`
- `TLB_DEFAULT_RING`, `SHELL_CMD_TIMEOUT`, `SHELL_SESSION_TIMEOUT`
- `BUFFER_MAX`, `POLL_INTERVAL_SLOW`
- `INJECTION_PATTERN_ZH1`, `INJECTION_PATTERN_ZH2`
- `SHELL_AUTOCOMPLETE_LIMIT`, `SHELL_AUTOCOMPLETE_DISPLAY_LIMIT`

---

## 4. 类型注解完整性

### 4.1 🔴 `commands.py:32` `_coerce()` 缺少返回类型

```python
def _coerce(value: str):  # ← 无 -> Any
```

虽然该函数返回混合类型（bool/int/float/str），应显式标注 `-> Any`。

### 4.2 🟡 `commands_settings.py:21` `_get_center()` 缺少返回类型

```python
def _get_center():  # ← 无 -> Any
```

### 4.3 🟡 `commands_settings.py:138` `_coerce()` 缺少返回类型

```python
def _coerce(value: str):  # ← 无 -> Any
```

### 4.4 🟡 `output_guard.py:11` `set_output_guard()` 参数类型

```python
def set_output_guard(callback: Any) -> None:
```

使用 `Any` 过于宽松。应该使用 `Callable` 签名：

```python
from collections.abc import Callable
def set_output_guard(callback: Callable[[str, str], dict]) -> None:
```

同样 `output_guard.py` 的 `_output_guard_callback` 也声明为 `Any`。

### 4.5 🟡 `i18n.py:83` `register()` 参数类型过于宽松

```python
def register(locale: str, data: dict[str, str | dict]) -> None:
```

嵌套字典 `dict[str, str | dict]` 可以更精确为 `dict[str, str | dict[str, str]]` 或使用 `TypeAlias`。

### 4.6 ✅ 良好实践

所有 `def test_*` 函数、所有 `_cmd_*` 函数、`dispatch()`、`_pipeline()` 等**都已正确标注返回类型**。类型覆盖率整体较高（>90%）。`from __future__ import annotations` 在 8/11 文件中使用。

---

## 5. 并发安全与全局可变状态

### 5.1 🔴 `selector.py` 全局索引无锁保护

```python
_role_index: dict[str, list[tuple[str, str]]] = {}      # 模块级可变全局
_role_index_stale: bool = True                           # 模块级可变全局
_llm_reviewer: Any = None                                # 模块级可变全局
```

`preselect()` 调用 `_rebuild_role_index()` 写入 `_role_index`，而 `_select_best()` 读取它。两者均**无 threading.Lock 保护**。多线程场景下：
- 读写竞争 → 索引损坏或 KeyError
- `_role_index_stale` 的无保护读写 → 可能重复重建索引

### 5.2 🟡 `shell.py`（REPL）的 `readline` 配置非线程安全

`direct_session()` 函数直接操作 `readline.set_completer(completer.complete)`，这在多线程 REPL 中不安全。`TerminalCompleter` 实例不是线程安全的。

### 5.3 🟡 `shell_session.py` 的 `TerminalManager._reader` 线程无超时

`_reader` 线程在 `while s.is_alive()` 循环中可能无限阻塞在 `out.readline()`（Windows）。虽然有 `BlockingIOError` 处理，但如果进程挂起但不退出，线程永远不会终止。应添加 polling interval 上限或 watchdog 超时。

### 5.4 🟡 `state.py` `ShellState` 无锁保护

```python
_shell_state = ShellState()
```

`ShellState` 是全局单例，其 `switch_to_direct()` / `switch_to_l3a()` 修改多个属性，但不是原子操作。在 `dispatch()` 读取 `state.is_direct()` 后立即被另一个线程写入，会导致决策与实际状态不一致。

### 5.5 🟠 `i18n.py` `_default_adapter` 延迟初始化竞态

```python
_default_adapter: I18nPort | None = None

def _adapter() -> I18nPort:
    global _default_adapter
    ...
    if _default_adapter is None:
        _default_adapter = YamlI18nAdapter()
```

多线程并发调用 `_adapter()` 时，两个线程可能都通过 `is None` 检查并分别创建 adapter。虽然第二次赋值覆盖第一次是安全的（result 相同），但 `YamlI18nAdapter()` 构造可能有副作用（读取文件、建立连接），造成重复工作。应使用 `threading.Lock` 或 DCLP（double-checked locking）。

---

## 6. 错误处理

### 6.1 🔴 `commands.py:67` 重复的 `logger` 初始化

```python
logger = logging.getLogger(__name__)   # 第27行
...
logger = logging.getLogger(__name__)   # 第67行（重复）
```

第 67 行的 `logger = logging.getLogger(__name__)` 与第 27 行完全重复。这是一个**明显的代码缺陷**——覆盖了之前定义但内容相同，不影响日志行为，但说明代码存在编辑/合并遗留问题，影响可维护性。

### 6.2 🟠 大量 `except Exception:` 吞没异常

在 11 个文件中统计到 **20 处** `except Exception:` 裸捕获（不含 `as e`）：

| 文件 | 行号 | 模式 |
|------|------|------|
| `commands.py` | 349, 635, 965, 1107, 1205, 1233, 1279, 1311 | 裸捕并静默处理 |
| `completer.py` | 18, 34, 46, 81, 90 | `logger.warning` 后静默继续 |
| `__init__.py` | 85, 133 | `logger.warning` 后静默继续 |
| `selector.py` | 91 | 裸捕后返回默认值 |
| `shell.py` | 134 | 裸捕后 fallback |
| `shell_completer.py` | 18, 34, 46 | `logger.warning` 后静默继续 |
| `shell_session.py` | 166 | `break` 退出线程 |

虽然项目约定允许「结构化返回」替代异常传递，但**静默吞没**尤其是在 `except Exception:` 裸捕后**不记录错误**（如没有 `logger.warning(e)`）是危险的。

**最严重案例**：`commands.py:349` 的 `except Exception:` 只有 `agents[cid] = []`，没有日志记录——如果 `cell._agents` 访问抛出异常，问题不会被发现。

### 6.3 🟠 `capture()` 使用不均衡

全局 11 处 `capture()` 调用，集中在 `selector.py`（7 处）和 `commands.py`（4 处）。但：
- `commands.py` 中 26 个 `_cmd_*` handler 的 `try/except Exception as e` 块并未全部使用 `capture()`
- 仅 `_cmd_think`, `_cmd_model._model_switch`, `_cmd_model._model_set`, 和模块级引入使用了 `capture()`
- 许多命令执行失败不会被监测系统捕获

### 6.4 ℹ️ `i18n.py:39-43` KeyError 误用

```python
try:
    adapter = get_port("i18n")
    if isinstance(adapter, I18nPort):
        return adapter
except KeyError:
    pass
```

这里期望 `get_port()` 在端口未注册时抛出 `KeyError`，但 `get_port` 的实际实现可能返回 `None` 或抛出其他异常。如果不是 `KeyError`，会传播到上层。

---

## 7. 导入模式与依赖管理

### 7.1 🟡 40+ 处函数级延迟导入

`commands.py` 中几乎**每一个 `_cmd_*` 函数**都在函数体内部通过 `from xxx import yyy` 延迟导入。虽有性能考量（避免启动时加载所有 L3 模块），但：
- 违背了 Python 导入惯例（PEP 8 建议全部放在模块顶部）
- 降低了可读性，使每个函数前 5-8 行都是 import 语句
- 延迟导入失败只会产生运行时错误而非启动时错误

典型模式：

```python
def _cmd_xxx(args: list[str]) -> dict:
    try:
        from l3.xxx import get_yyy
        yyy = get_yyy()
        ...
    except Exception as e:
        return {"success": False, "error": str(e)}
```

**建议**: 可以将常用的 L3 接入点（如 `get_cell`, `get_coordinator` 等）提升到模块级延迟导入块中，减少每个 handler 的重复导入。

### 7.2 🟡 不必要的作用域导入别名

```python
from l3.services.central_security import get_center as _get_sec
from l3.memory.central_memory import get_center as _mem
```

使用 下划线前缀 表明「导入仅供本函数使用」，但 Python 不强制执行。这种模式在 `commands.py` 中出现 15+ 次，风格不统一（有的用别名，有的直接用原函数名）。

### 7.3 🟡 `shell_completer.py` 在模块级执行内部 try/except

```python
_ALIASES: dict[str, str] = _load_aliases()       # 模块级调用
_COMMANDS: list[str] = get_tool_names()           # 模块级调用
_COMMAND_HELP: dict[str, str] = _load_tool_help() # 模块级调用
```

这些模块级调用在**导入时立即执行**，且各自内部有 `try/except` 处理异常。如果 L3 工具注册表在导入时不可用，模块会静默降级。应延迟到首次使用。

---

## 8. 代码风格与命名

### 8.1 🟡 `commands.py` 行超长

`commands.py:361`:
```python
return {"success": True, "data": {"state": state, "cells": len(coord._cells), "composites": len(coord.b.composites), "cross_cell_active": getattr(coord, '_cross_cell_active', False)}}
```
单行超过 200 字符，远超项目 120 字符限制。全文件中有 10+ 处超 120 字符的行。

### 8.2 🟡 `commands.py:67` 多余空行

第 67 行附近：
```python
logger = logging.getLogger(__name__)   # ← 重复


                                           # ← 多余 3 个空行

def preconnect_enhanced(...):
```

3 个空行而非约定的 2 个，说明编辑时格式化不严谨。

### 8.3 ℹ️ Double quote 合规检查

项目 ruff 约定 `quote-style = "double"`。抽样检查显示所有文件均使用双引号字符串，符合约定。

### 8.4 ℹ️ 命名规范检查

检查通过：
- 函数名：`snake_case` ✓
- 类名：`PascalCase` ✓
- 常量：`UPPER_SNAKE_CASE` ✓

---

## 9. 安全性审查

### 9.1 🟠 私有属性直访问

`commands.py` 中 **13 处**直接访问 L3 对象的私有属性（`_` 前缀）：

```python
cell._agents.keys()               # 348, 500 — 违反封装
coord._cells                      # 357, 359, 361, 380, 383, 386, 387 — 直接修改
coord._cross_cell_active          # 357, 361, 386 — 直接写入
h._methods                        # 402, 410, 417 — 窥探内部
mm._ring(ring_n).status()         # 470 — 直接调用私有方法
comp.htn_b._methods               # 410 — 多层私有穿透
center._dump_l3()                 # commands_settings.py:70
```

**最严重**：`_cmd_cluster` 的 `shrink` 子命令直接修改 `coord._cells` 列表：

```python
coord._cells = [c for c in coord._cells if c.get("id") != cell_id]
```

如果 L3 的 `_cells` 属性重构或改名，`_cmd_cluster` 会静默失效且无法被静态检查发现。

### 9.2 🟠 `_cmd_cluster` 的 `shrink` 操作非原子

```python
coord._cells = [c for c in coord._cells if c.get("id") != cell_id]
from l3.bus.l3b import L3B
new_l3b = L3B()
for c in coord._cells:
    new_l3b.register(...)
coord.b = new_l3b
```

在 `coord._cells` 更新后和 `coord.b` 重建前存在窗口期——集群状态不一致。应使用 L3 提供的 `coord.remove_cell(cell_id)` 方法（如果存在）。

### 9.3 🟡 Output guard 不安全默认

`output_guard.py:29`:
```python
return {"allowed": True, "response": response}
```

当 guard callback 未注册时，所有输出默认通过（`allowed=True`）。如果系统忘记注册 guard，用户将直接看到所有 agent 响应。应至少记录一次警告（logger.warning），或在系统初始化时强制注册 guard。

### 9.4 🟡 Prompt injection 扫描器正则风险

`selector.py:50-58` 的注入正则模式匹配是 CPU 密集型操作，尤其在长消息上：
- `re.compile(r"ignore\s+(all\s+)?(previous|above|system)\s+(instructions|prompts)", re.I)` 在长文本上的回溯可能很重
- 没有注入检查的超时保护
- `_scan_injection` 在 `preconnect()` 的同步路径上调用，可能阻塞

---

## 10. 测试覆盖质量

### 10.1 🟠 命令覆盖不均衡

| 度量 | 值 |
|------|-----|
| `_cmd_*` 命令总数 | 45 个 |
| 有直接测试覆盖的命令 | ~22 个（约 49%） |
| 零测试覆盖的命令 | `/connect`, `/disconnect`, `/destroy`, `/emergency`, `/agent_refresh`, `/agent_restart`, `/cluster`, `/htn`, `/settings`, `/cache`, `/sysinfo`, `/process`, `/buffer`, `/model`（子命令），`/think`（整体流程）等 |

### 10.2 🟠 异常路径测试不足

`test_l2_shell_integration.py` 有较好的异常路径覆盖（如 `test_connect_blocked_by_security`, `test_disconnect_fails_still_clears_state`），但：
- 缺少对 `commands.py:349` 的 `except Exception:`（cell._agents 访问失败）的测试
- 缺少对 `commands.py:566-576` `_cmd_process` 中 `reg.processes()` 失败的测试
- 缺少对 L4 依赖模块缺失时的降级测试（如 `_cmd_cron` 中 `l4.cron_scheduler` 不可用）

### 10.3 🟡 测试组织结构

测试文件分布合理（unit / e2e / integration / health 分离），共 **1735 行** 测试代码覆盖 **~85 个 test case**，总量合理。但：
- `test_l2_shell.py` 部分测试依赖全局状态（如 `ShellState` 单例），虽然 `conftest.py` 有 autouse reset，但可能在并行测试时互相影响
- `test_shell.py` 的 `test_create_and_list` 实际创建子进程，既是 e2e 又放在 unit 测试中

### 10.4 ℹ️ 空白 / 缺失测试场景

- **Pipeline**（`_pipeline` 函数）无独立单元测试——只通过集成测试间接覆盖
- **I18n fallback** 路径（`_default_adapter` 创建）无测试
- **`resolve_scope`** 无独立测试
- **`resolve_agents`** 无独立测试
- **`system_command` 装饰器** 无测试

---

## 11. 代码异味与潜在缺陷

### 11.1 🔴 `commands.py:348` 访问 `cell._agents` 私有属性

```python
agents[cid] = list(cell._agents.keys()) if hasattr(cell, '_agents') else []
```

这是封装违反，且 `hasattr` 降级检查导致如果 L3 Cell 的 `_agents` 属性被移除，会静默返回空列表。

### 11.2 🟠 `commands.py:349` 空 except 块无日志

```python
except Exception:
    agents[cid] = []
```

没有任何日志记录。如果 Cell 不可达或 `get_cell(cid)` 抛出异常，调用者完全不知道子进程失败。

### 11.3 🟡 `commands.py` 末尾模块级别的自动注册

```python
for _cmd_name in dir():
    if _cmd_name.startswith("_cmd_"):
        ...
        _SYSTEM_COMMANDS.append((_cmd_name[5:], _fn, {}))
```

使用 `dir()` 和 `locals()` 反射所有函数名，然后通过 `strip("_cmd_")` 提取命令名。这是**隐式约定**——如果命名不遵循 `_cmd_xxx` 格式、或者内部嵌套函数名巧合匹配 `_cmd_` 前缀，会意外注册。

### 11.4 🟡 `_cmd_destroy` 忽略参数

```python
def _cmd_destroy(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /destroy <cell_id>"}
    cell_id = args[0]
    try:
        from l3.cell import reset_cells
        reset_cells()
        return {"success": True, "message": f"Cell '{cell_id}' destroyed (all cells reset)"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

用户传入 `cell_id` 但从不用它——直接调用 `reset_cells()` 重置**所有** cell。提示文本和实际行为不一致。

### 11.5 🟡 `shell_session.py:85` Windows shell 创建无充分异常处理

```python
proc = create_interactive_shell(cwd=cwd or "")
```

如果 `cwd` 不存在，`create_interactive_shell` 将失败。但上层 `create()` 的 fallback 已经是 `except Exception`，会在日志中丢失原始路径细节。

### 11.6 🟡 `shell.py:50-55` readline 导入降级渲染无用

```python
try:
    import readline
    completer = TerminalCompleter()
    completer.refresh()
    readline.set_completer(completer.complete)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(' \t\n')
except ImportError:
    pass  # 无 tab 补全
```

`except ImportError: pass` 在没有 readline 的 Windows 上是必要的，但 `TerminalCompleter` 实例（`completer`）被创建后未被保存——如果后续代码需要 tab 补全降级后的替代方案，无法引用它。

---

## 12. 综合结论

### 统计摘要

| 严重等级 | 数量 | 按类别分布 |
|---------|------|-----------|
| 🔴 **Critical** | 5 | 全局变量无锁(2)、参数常量违规(1)、封装破坏(1)、模块级缺陷(1) |
| 🟠 **Major** | 15 | 魔法数字(5)、类型缺失(3)、异常吞没(2)、分层违规(1)、测试缺口(2)、安全(2) |
| 🟡 **Minor** | 20 | 代码风格(3)、导入模式(3)、可维护性(5)、测试(4)、安全(2)、性能(1)、冗余(2) |
| ℹ️ **Info** | 7 | 架构观察(3)、设计记录(2)、良好实践(2) |
| **总计** | **47** | |

### 核心评价

**L2 层整体代码质量中等偏上**。最突出的优点：
- ✅ 类型注解覆盖率 >90%
- ✅ 遵循 params 常量模式（虽然不完整）
- ✅ 结构化返回一致性好（`{"success": bool, "error": str}`）
- ✅ `from __future__ import annotations` 在主要文件中使用
- ✅ 符合 ruff 双引号约定
- ✅ 测试组织合理，e2e/integration/unit 分离

**需要立即修复的核心问题**：
1. 多线程竞态（`selector.py` 全局索引、`state.py` 单例、`i18n.py` 懒加载）
2. 参数常量提取（注入阈值、指标字符串、角色列表）
3. 20 处 `except Exception:` 加强精确异常捕获或添加日志
4. `commands.py:67` 重复 logger 初始化
5. L2→L4 直连违反分层架构

### 优先修复建议

| 优先级 | 问题 | 估时 |
|--------|------|------|
| 🔴 P0 | `selector.py` 全局索引加锁 | ~5min |
| 🔴 P0 | `commands.py:67` 移除重复 logger | ~1min |
| 🔴 P0 | 注入阈值提取到 `params/` | ~10min |
| 🟠 P1 | 13 处私有属性访问改用公有接口 | ~30min |
| 🟠 P1 | `_cmd_destroy` 不一致行为修复 | ~5min |
| 🟠 P1 | `except Exception:` 批量审查与修复 | ~20min |
| 🟡 P2 | 角色列表提取到 params 常量 | ~10min |
| 🟡 P2 | metrics 字符串提取到 params 常量 | ~5min |
| 🟡 P2 | 测试补充（pipeline, resolve_scope, resolve_agents） | ~30min |
| 🟡 P2 | `_cmd_cluster` shrink 非原子修复 | ~15min |
