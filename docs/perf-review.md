# 性能审查报告（全层）

> **审查日期**: 2026-07-30 | **审查范围**: L1 Kernel → L4 Bridge 热路径性能
> **审查方法**: 源码分析 + 复杂度分析 + 热路径追踪

---

## 目录

1. [syscall 调度与审计](#1-syscall-调度与审计)
2. [分配器与资源管理](#2-分配器与资源管理)
3. [调度器与进程表](#3-调度器与进程表)
4. [锁粒度与轮询间隔](#4-锁粒度与轮询间隔)
5. [异步事件分发](#5-异步事件分发)
6. [I/O 与连接池](#6-io-与连接池)
7. [综合评分与优化建议](#7-综合评分与优化建议)

---

## 1. syscall 调度与审计

### 1.1 `syscall()` 分发

```python
handler = _SYSCALL_REGISTRY.get(op)   # O(1) 字典查找
```

**复杂度: O(1)** ✅ — 字典查找，无瓶颈。

### 1.2 `_audit()` 审计日志

```python
# 线程本地缓冲 + 批量刷新
buf = getattr(_thread_audit_buffer, "entries", None)
buf.append(entry)
if len(buf) >= AUDIT_FLUSH_SIZE:      # 32条一批
    with _audit_lock:
        _audit_log.extend(buf)         # deque(maxlen=5000) O(1)
```

**评价: 🟢 优秀设计**
- 线程本地缓冲避免每次 syscall 竞争全局锁
- 每 32 次 syscall 才获取一次 `_audit_lock`
- `deque(maxlen=5000)` 自动 O(1) 修剪
- 多线程下锁竞争频率 = `LOCK_ACQ / (THREADS × 32)`，可忽略

---

## 2. 分配器与资源管理

### 2.1 `Allocator.alloc()` 热路径

```python
def alloc(self, agent_id, resource, amount):
    with self._lock:                              # RLock 可重入
        ...
        used = sum(a.amount for a in allocs       # O(N) 线性扫描！
                   if a.resource == resource)
```

**复杂度: O(N)** ⚠️ — N 是该 agent 的历史全部分配记录数。

- 每次 `alloc()` 都遍历全部历史记录计算当前用量
- 如果单 agent 有数千次分配（Ring 1/2/3 条目），每次工具调用扫描代价累积
- 压力缓存在每一次 alloc/free 后被 invalidated（`_pressure_cache = None`）

**建议**: 维护每个 agent × resource 的累计用量计数器，避免每次都 O(N) 扫描。

```python
# 建议方案
self._usage_counter: dict[str, dict[str, int]] = {}  # agent_id → {resource: used}

def alloc(self, ...):
    used = self._usage_counter.setdefault(agent_id, {}).get(resource, 0)
    ...
    self._usage_counter[agent_id][resource] = used + amount
```

### 2.2 `ResourceLimiter` ✅

| 方法 | 复杂度 | 评价 |
|------|--------|------|
| `check()` | O(1) | 字典查找，无循环 |
| `release()` | O(1) | 字典更新 |
| `usage()` | O(1) | 字典读取 |

资源限制器**没有性能问题**。使用 RLock 保护，临界区极小。

---

## 3. 调度器与进程表

### 3.1 ProcessTable ✅

| 操作 | 复杂度 | 说明 |
|------|--------|------|
| `spawn()` | O(1) | 字典插入 + `_name_index` 更新 |
| `get(pid)` | O(1) | 字典查询 |
| `get_by_name(name)` | O(1) | `_name_index` 字典查询 |
| `exit()` | O(1) | 字典删除 + 审计记录 |
| `list()` | O(N) | N ≤ `PROCESS_TABLE_MAX=500`，可接受 |

**评价: 🟢 良好**。500 进程上限意味着最差 O(500) 扫描也可接受。

### 3.2 Scheduler

```python
def schedule(self, agent_ids: list[str]) -> str | None:
    return random.choice(agent_ids) if agent_ids else None
```

**复杂度: O(1)** ✅ — 随机选择，无排序或加权。

---

## 4. 锁粒度与轮询间隔

### 4.1 同步原语参数

| 原语 | 轮询间隔 | 超时 | 评价 |
|------|---------|------|------|
| **Mutex** | 50ms | 30s | 🟢 合理，不浪费 CPU |
| **Semaphore** | 100ms | 30s | 🟢 宽松，100ms 对信号量够用 |
| **RWLock** | 50ms | 30s | 🟢 合理 |
| **Barrier** | — | 60s | 🟢 一次性等待，无轮询 |

`_cond.wait(timeout=min(remaining, 0.5))` 使用 `threading.Condition` 的 wait 而非忙等——**不消耗 CPU** ✅

### 4.2 全局锁热点

| 锁 | 位置 | 竞争频率 | 评价 |
|----|------|---------|------|
| `_audit_lock` | `__init__.py` | 低（每 32 syscall/线程） | 🟢 批量刷新减少竞争 |
| `event._bus._lock` | `event.py` | 中等 | 🟢 临界区极小（list copy + append） |
| `allocator._lock` | `allocator.py` | 高 | 🟡 持有期间做 O(N) 扫描（见 2.1） |
| `process._table_lock` | `process.py` | 低 | 🟢 O(1) 操作 |
| `gatechain._lock` | `gatechain.py` | 低 | 🟢 注册时使用，非热路径 |

**最需关注**: `allocator._lock` 持有期间执行的 O(N) `sum()` 扫描。

---

## 5. 异步事件分发

### 5.1 EventBus（`event.py`） ✅

```python
self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="evt")

def emit(self, signal):
    with self._lock:                       # 锁仅保护list copy
        callbacks = list(self._listeners.get(signal.type, []))
    for cb in callbacks:
        self._executor.submit(self._safe_call, cb, signal)  # 非阻塞
```

**评价: 🟢 优秀**
- 锁仅用于 `list()` 复制，不阻塞回调执行
- `max_workers=4` 足够应对典型场景
- shutdown 后回退同步模式，优雅降级

### 5.2 MonitorBus（`monitor_bus.py`） ✅（已修复）

```python
self._executor = ThreadPoolExecutor(max_workers=2, ...)
self._bounded_submit(self._append_persist, event)  # 有界提交
```

**评价: 🟢 优秀**
- Ring buffer append 保持同步 O(1) ✅
- JSONL 持久化移到后台线程 ✅
- SSE 回调也异步，不阻塞 emitter ✅
- 添加 `_MAX_QUEUED=200` 有界提交，防止无限积压 ✅

---

## 6. I/O 与连接池

### 6.1 🟡 无 HTTP 连接池（全层）

所有 HTTP 客户端使用 **`urllib.request`**（stdlib），不支持连接池：

| 位置 | 文件 | 影响 |
|------|------|------|
| **LLM 调用** | `llm_providers.py` | 每次 LLM 推理都新建 TCP 连接 + TLS 握手 |
| **网络请求** | `network.py` | 每次 API 调用新建连接 |
| **MCP 调用** | `mcp_bridge.py` | 每次 MCP 工具调用新建连接 |
| **CI 构建** | `ci.py` | 不受影响（subprocess） |
| **Git 操作** | `git.py` | 不受影响（subprocess） |

**影响最大的路径**: `agent_loop.py` → `LLMEngine.generate()` → `OpenAIProvider._api_call()`

每次 LLM 调用：
1. DNS 查询
2. TCP 三次握手
3. TLS 1.3 握手（1-RTT）
4. HTTP 请求/响应

没有连接池意味着**每个 LLM 调用的网络往返额外增加 50-150ms**。

**建议**: 为 LLM provider 引入连接池。若需保持零外部依赖，可以用 `urllib.request` 的 `HTTPConnectionPool` 或改用 `httpx`（支持 HTTP/2 + 连接池）。

### 6.2 子进程管理 ✅

- `supervisor.py` 使用 `subprocess.Popen` + 后台 monitor 线程
- `sandbox/manager.py` 使用 `asyncio.create_subprocess_exec` + 临时目录自动清理
- 子进程超时设置合理（`CI_SHELL_TIMEOUT`, `SANDBOX_DEFAULT_TIMEOUT` 等）

---

## 7. 综合评分与优化建议

### 7.1 性能评分矩阵

| 子系统 | 热路径复杂度 | 锁竞争 | 可优化空间 | 评分 |
|--------|:----------:|:------:|:---------:|:----:|
| syscall dispatch | O(1) | 低 | 无 | 🟢 **10/10** |
| audit log | O(1) 批量 | 极低 | 无 | 🟢 **10/10** |
| allocator | **O(N)** | 中 | 累计计数器 | 🟡 **7/10** |
| resource limiter | O(1) | 低 | 无 | 🟢 **10/10** |
| process table | O(1)~O(500) | 低 | 无 | 🟢 **9/10** |
| scheduler | O(1) | 低 | 无 | 🟢 **10/10** |
| Mutex/Semaphore | O(1) | 中 | 无 | 🟢 **9/10** |
| EventBus | O(C) async | 低 | 无 | 🟢 **10/10** |
| MonitorBus | O(1) async | 低 | 无 | 🟢 **9/10** |
| **HTTP 连接池** | N/A | N/A | **新建每次连接** | 🟡 **5/10** |

### 7.2 优化优先级

| 优先级 | 问题 | 影响 | 估时 |
|--------|------|------|------|
| **P0** | `Allocator.alloc()` 行 99 O(N) 扫描——每次分配遍历全量历史 | agent 工具调用热路径，N 越大越慢 | ~10min |
| **P1** | HTTP 无连接池（`urllib.request`）——每次 LLM 调用 +50~150ms TLS 开销 | 全层所有 HTTP 调用 | ~30min（可引入 `httpx`） |
| **P2** | `EventBus` 无界 `ThreadPoolExecutor` 队列（同 monitor_bus 修复前模式） | 极端负载下内存增长 | ~5min |
| **P3** | `allocator._pressure_cache` 每次 alloc/free 清空，高频分配下压力检测永远不命中缓存 | 高负载场景 | ~2min |

### 7.3 核心结论

| 维度 | 结论 |
|------|------|
| **整体性能** | 🟢 **良好** —— 核心路径复杂度均在 O(1) |
| **最大瓶颈** | 🟡 `Allocator.alloc()` 的 O(N) 扫描 + 全层 HTTP 无连接池 |
| **并发控制** | 🟢 优秀 —— 线程本地缓冲批量刷新，`_cond.wait()` 不忙等 |
| **异步设计** | 🟢 优秀 —— EventBus 和 MonitorBus 均异步派发，不阻塞热路径 |
| **需要优化的行数** | **约 5 行代码**（累加计数器 + 有界队列） |

**一句话**: 性能基线良好，两个关键优化点（O(N) alloc 扫描 + HTTP 连接池）可带来显著收益。
