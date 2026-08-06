# 总线数据流审查报告

> **审查日期**: 2026-07-30
> **审查范围**: 全项目 20 个总线相关文件（L1:3 + L3:17）
> **审查方法**: 逐文件数据流追踪 + 拓扑关系分析

---

## 目录

1. [总线全景图](#1-总线全景图)
2. [L1 Kernel 总线](#2-l1-kernel-总线)
3. [L3 Cell 总线](#3-l3-cell-总线)
4. [总线拓扑关系](#4-总线拓扑关系)
5. [数据流交叉分析](#5-数据流交叉分析)
6. [关键发现与建议](#6-关键发现与建议)

---

## 1. 总线全景图

```
L1 Kernel 层                          L3 Cell 层
═══════════════════                  ═══════════════════════════════════
                  │
  EventBus        │──emit_signal()──→  事件驱动
  (event.py)      │                     ├─ MonitorBus (监控/告警)
                  │                     ├─ ErrorBus (错误采集)
                  │                     ├─ ObservabilityBus (可观测汇总)
  SystemBus       │                     └─ MessageGate (策略过滤)
  (bus.py)        │──mount()──────→  组件生命周期
                  │
  LockBus         │──send()/request()→ 同步原语
  (ipc.py)        │                     └─ L3 IpcBus (跨进程消息)
                  │
                  │                     跨 Cell 总线
                  │                     ├─ L3B (复合路由)
                  │                     ├─ L3BBus (消息路由)
                  │                     ├─ L3BMessagePool (缓存+持久化)
                  │                     ├─ HTN-A (全局分解)
                  │                     └─ HTN-B (跨Cell路由)
                  │
                  │                     数据采集
                  │                     ├─ ReferenceChannel (JSONL)
                  │                     ├─ TaskBus (Webhook)
                  │                     └─ CommMonitor (通信采样)
```

---

## 2. L1 Kernel 总线

### 2.1 EventBus — 发布/订阅事件总线

**文件**: `src/l1/kernel/event.py` (202 行)
**数据流**: `emit(signal)` → 同步写 history → 异步 ThreadPool dispatch

```
  ┌─ signal ─────────────────────────────────────────┐
  │  Signal {type, data, sender, target, timestamp}  │
  └──────────────────────────────────────────────────┘
          │
          ▼
  ┌─ EventBus ───────────────────────────────────────┐
  │  1. with RLock: append to _history (deque)       │
  │  2. snapshot _listeners + _wildcard_listeners     │
  │  3. _executor.submit(_safe_call, cb, signal)     │
  └──────────────────────────────────────────────────┘
          │                                          │
          ▼                                          ▼
  typed listeners                           wildcard listeners
  (by SignalType enum)                     (all signals)
```

| 维度 | 值 |
|------|-----|
| 信号量 | 19 种内置 SignalType + 动态扩展 |
| 线程池 | 4 workers（EVENT_BUS_WORKERS） |
| 历史 | deque(maxlen=EVENT_MAX_HISTORY) |
| 锁 | `RLock` 保护全部操作 |
| 关闭模式 | shutdown 后切换到同步 dispatch |
| 单例 | `_bus = EventBus()` 模块级 |

**数据流特点**:
- ✅ 写 history 和 dispatch 在锁内保持原子性
- ✅ ThreadPool 隔离避免回调阻塞 emitter
- ✅ `_safe_call` 包裹每个回调防止单个异常扩散
- ⚠️ 历史查询 `history()` 使用 `[-limit*2:]` magic factor

### 2.2 SystemBus — 组件生命周期总线

**文件**: `src/l1/kernel/bus.py` (426 行)
**数据流**: `register()` → `install()` → `start_all()` → `emit()` → `stop_all()`

```
  Component(ABC)           SystemBus
  ┌─────────────────┐      ┌────────────────────────┐
  │ bus_init(bus)   │─────▶│ _components[name]      │
  │ bus_start()     │─────▶│ _children[name]        │
  │ bus_stop()      │◀────│ topological_sort →      │
  │ bus_health()    │      │   start/stop in order   │
  │ bus_stats()     │      │                        │
  └─────────────────┘      │ _emit_downward(event)  │
          ▲                └────────────────────────┘
          │ mount(name)
    SystemBus(child)
    ┌────────────────┐
    │ _children[name]│
    └────────────────┘
```

| 维度 | 值 |
|------|-----|
| 组件模型 | ABC 基类（5 个生命周期钩子） |
| 层级 | 树形（parent-child via mount） |
| 事件 | `emit(event, data, source)` → 向下传播 + 通配符匹配 |
| 启动顺序 | 拓扑排序（基于 `depends_on`） |
| 单例 | `get_root_bus()` |

**数据流特点**:
- ✅ 组件生命周期管理完整（init → start → health → stats → stop）
- ✅ 拓扑排序保证依赖顺序
- ✅ `_emit_downward` 向子组件传播（但**不向上**）

### 2.3 IPC Bus — 进程间同步消息通道

**文件**: `src/l1/kernel/ipc.py` (148 行)
**数据流**: `send(msg)` → handler 回调 / `request(msg, timeout)` → Event.wait

```
  LockChannel                  LockBus
  ┌────────────────┐           ┌──────────────────┐
  │ _queue: deque   │           │ _channels[dict]  │
  │ _handlers:[]    │           │ with Lock        │
  │ _responses:{}   │          └──────────────────┘
  │ _response_events│                  │
  └──────┬─────────┘           get_channel(name)
         │
  send(msg) → handler(msg) → reply
  request(msg, timeout) → Event.wait() → response
```

| 维度 | 值 |
|------|-----|
| 消息 | `LockMessage{op, lock_name, agent_id, priority, timestamp, msg_id}` |
| 操作 | ACQUIRE / RELEASE / STATUS / BOOST |
| 通道 | 每个同步原语一条专用通道 |
| 寻址 | 通道名（`name:msg_type`） |
| 超时 | `IPC_REQUEST_TIMEOUT` |
| 单例 | `get_lock_bus()` with DCLP ✅ |

**数据流特点**:
- ✅ 请求/响应模式完整
- ✅ `request()` 超时路径清理 `_response_events` 防止内存泄漏
- ✅ `get_lock_bus()` 使用正确的 DCLP（`_lock_bus_lock`）
- ⚠️ handler 抛出异常时仅 `logger.error` 不会破坏通道

---

## 3. L3 Cell 总线

### 3.1 MonitorBus — 统一监控事件总线

**文件**: `src/l3/bus/monitor_bus.py` (220 行)
**数据流**: `emit(MonitorEvent)` → JSONL 持久化 → ring buffer → SSE

```
  ┌─ MonitorEvent ────────────────────────────────────────────┐
  │ {type, source, severity, agent_id, cell_id, card_id,      │
  │  message, data, timestamp}                                │
  │  例: "network.peer.join", "service.cell.crash", ...       │
  └───────────────────────────────────────────────────────────┘
          │
          ▼
  ┌─ MonitorBus ──────────────────────────────────────────────┐
  │  1. _append_persist() → JSONL file (sync append)          │
  │  2. with RLock: ring.append(event)                        │
  │  3. SSE callbacks (sync, iter _sse_listeners)             │
  └───────────────────────────────────────────────────────────┘
          │
          ▼
  ┌─ query() ─────────────────────────────────────────────────┐
  │  过滤: type_prefix(glob), severity, agent_id, cell_id,    │
  │        source, since → ring buffer (reversed scan)        │
  └───────────────────────────────────────────────────────────┘
```

| 维度 | 值 |
|------|-----|
| 事件模型 | `MonitorEvent`（9 字段） |
| 持久化 | JSONL 追加（`_append_persist`） |
| 启动恢复 | `_rehydrate()` 从 JSONL 加载到 ring |
| 环形缓冲 | `deque(maxlen=MONITOR_RING_SIZE)` |
| SSE | `subscribe_sse(callback)` 实时推送 |
| 查询 | 前缀通配符 + 多维度过滤 |
| 锁 | `RLock` |
| 单例 | `get_bus()` |

**数据流特点**:
- ✅ 持久化路径：emit → JSONL → ring → SSE （IO 在 emit 路径上同步）
- ✅ 启动恢复（rehydrate）：从 JSONL 重建历史
- ⚠️ JSONL 写入在 emit 同步路径上（可能阻塞 emitter）
- ⚠️ SSE callback 也在 emit 同步路径上（可能阻塞 emitter）

### 3.2 L3 IpcBus — 跨进程消息总线

**文件**: `src/l3/bus/ipc.py` (325 行)
**数据流**: `send(msg)` → channel deque → poll/subscribe

```
  ┌─ IPCMessage ─────────────────────────────────────┐
  │ {sender, target, msg_type, payload, priority,    │
  │  expires_at, trace_id, ttl}                      │
  └──────────────────────────────────────────────────┘
          │
          ▼
  ┌─ IpcBus (BaseService) ───────────────────────────┐
  │  send(msg) → route → _channels[cell:type] deque  │
  │  broadcast(msg) → all channels                   │
  │  poll(agent_id) → matching msgs                  │
  │  subscribe(msg_type, callback)                   │
  │  route_cross_cell(msg, target_cell)              │
  └──────────────────────────────────────────────────┘
          │
          ▼
    MessageType(Enum): TASK, REVIEW, RESULT, SCOUT_REPORT,
                       HEARTBEAT, DISPUTE, DIRECT, SYSTEM
```

| 维度 | 值 |
|------|-----|
| 支持 8 种消息类型 | TASK, REVIEW, RESULT, SCOUT_REPORT, HEARTBEAT, DISPUTE, DIRECT, SYSTEM |
| 通道 | `{cell_id}:{msg_type}` 组成队列 keys |
| 路由 | `route_cross_cell()` 跨 Cell 转发 |
| 订阅 | 按 MessageType 注册 callback |
| 便利方法 | `send_task()`, `send_review()`, `send_scout_report()`, `send_heartbeat()` |

### 3.3 L3B + L3BBus — 跨 Cell 协调总线

**文件**: `src/l3/bus/l3b.py` (298 行) + `src/l3/bus/l3b_bus.py` (241 行)
**拓扑**: 链式拓扑（N-1 个 composites 连接 N 个 Cell）

```
  Cell-1 ↔ [L3B_1_2] ↔ Cell-2 ↔ [L3B_2_3] ↔ Cell-3 ↔ ...
             │
         L3BBus(消息路由)
             │
  ┌─ L3BBus ──────────────────────────────────────────┐
  │  每个 composite 一个 mailbox (deque maxlen=200)    │
  │  send(sender, target, type) → mailbox.append       │
  │  read(composite_id) → mailbox 轮询                 │
  │  _find_relay() → 中间转发（链式）                   │
  │  约束：仅相邻 composite 可直接通信                   │
  └───────────────────────────────────────────────────┘
```

**L3BMessage 数据流**:

```
  L3BMessage{msg_id, msg_type, sender, target, payload, timestamp, ttl}
      │
      ▼
  L3BMessagePool(每个 composite 一个实例)
  ┌───────────────────────────────────────────────────┐
  │  push() → Hot Ring (deque maxlen)                 │
  │    → watermark ≥ 80% → _persist_one(SQLite)       │
  │    → backlog ≥ threshold → BACKPRESSURE signal    │
  │  pop() → Hot Ring (消费)                           │
  │    → 不足 → _restore_from_db() (补充)              │
  └───────────────────────────────────────────────────┘
```

**三级缓存策略**:

```
  hot ring (内存) ──watermark 80%──▶ SQLite persist
      │                                    │
      ◀─────── _restore_from_db ────────────
```

| 维度 | 值 |
|------|-----|
| 复合体 | `L3BComposite{prev_cell, next_cell, htn_b, active}` |
| 消息类型 | CARD_FORWARD, RESULT_BACK, STATUS_CHECK, BACKPRESSURE, HEARTBEAT |
| 消息缓存 | Hot Ring(deque) + SQLite persist |
| 反压 | persist backlog ≥ threshold → BACKPRESSURE |
| TTL | `SCOUT_POOL_IDLE_TIMEOUT` |
| 寻址 | composite_id（`l3b-{prev}-{next}`） |

**数据流特点**:
- ✅ 链式拓扑约束（仅相邻通信）防止路由循环
- ✅ TTL 过期自动丢弃
- ✅ 反压信号防止上游压垮下游
- ✅ Hot Ring + SQLite 两级缓存保证数据不丢

### 3.4 HTN-A / HTN-B — 任务分解总线

**文件**: `src/l3/bus/htn_a.py` (230 行) + `src/l3/bus/htn_b.py` (154 行) + `src/l3/bus/htn_planner.py` (453 行)

```
  HTN-A (全局)                 HTN-B (每 composite)
  ┌─────────────────────┐      ┌────────────────────────┐
  │ Intent → decompose   │      │  HTN-A subtask → route │
  │ Cell-1: design       │      │  prev_cell cache check │
  │ Cell-2: implement    │      │  next_cell dispatch    │
  │ Cell-3: verify       │      └────────────────────────┘
  └─────────────────────┘               │
          │                     L3B.bus → dispach_to_next
          ▼
  ┌─ CentralController ─────────────────────────────────┐
  │ get_shards(root) → flatten → group_by(cell_id)      │
  │   → [{cell_id, tasks}, ...]                         │
  └─────────────────────────────────────────────────────┘
```

| 维度 | 值 |
|------|-----|
| HTN-A | `DecompositionMethod{name, domain, patterns, decompose_fn}` |
| HTN-B | 约束：只读 prev_cell L2 cache / 只发 next_cell |
| Task 模型 | `{id, type(PRIMITIVE|COMPOUND), domain, agent_id, depends_on}` |
| 注册方法 | `pipeline_full`, `pipeline_fix`, `pipeline_review` + `route_forward`, `merge_back` |

### 3.5 ReferenceChannel — 可观测数据记录

**文件**: `src/l3/bus/reference_channel.py` (290 行)
**数据流**: `event(type, data)` → ring buffer → 后台线程 flush → JSONL

```
  event("tool_call", {...})              _flush_loop(daemon)
       │                                      │
       ▼                                      ▼
  ring buffer (deque) ──periodic(5s)──▶ JSONL append
       │
       └── SHA-256 hash appended to each record

  便利方法:
    tool_call(), card_lifecycle(), human_correction(),
    anomaly(), convention()
```

| 维度 | 值 |
|------|-----|
| 记录类型 | tool_call, card_lifecycle, gatechain, human_correction, convention, anomaly |
| 持久化 | JSONL + SHA-256 内容哈希 |
| 环形缓冲 | `deque(maxlen=RC_RING_SIZE)` |
| 刷新 | 后台 daemon 线程（`RC_FLUSH_INTERVAL`） |
| 超时回退 | flush 失败时 `extendleft(reversed(lines))` 重入队列 |
| 单例 | `get_rc()` with DCLP ✅ |

### 3.6 ErrorBus — 统一错误总线

**文件**: `src/l3/error_bus/__init__.py` (726 行)
**数据流**: `capture(msg, exc, context)` → 指纹去重 → LogService + EventBus + SSE

```
  capture("memory compact failed", exc=e, component="services")
       │
       ▼
  ┌─ ErrorBus ──────────────────────────────────────────────────┐
  │  1. _compute_fingerprint() → 去重 (ERROR_BUS_DEDUP_WINDOW)  │
  │  2. ErrorLogEntry(code, message, exc, context)              │
  │  3. write to LogService + emit to EventBus + SSE push       │
  └─────────────────────────────────────────────────────────────┘
       │
       ▼
  日志文件 / API 查询 / SSE 实时流
```

### 3.7 ObservabilityBus — 可观测聚合门面

**文件**: `src/l3/bus/observability_bus.py` (150 行)
**数据流**: `observe(kind, source, data)` → 四路分发

```
  observe("alert", source, data)   → ops_console.add_alert()
  observe("health", source, data)  → l1.kernel.health.health()
  observe("metric", source, data)  → services.counter.increment()
  observe("audit", source, data)   → l1.kernel.record_audit()
```

无缓冲、无持久化、纯路由。4 个方法全部使用 `try/except Exception` 降级。

---

## 4. 总线拓扑关系

### 4.1 事件驱动链路

```
  L1 EventBus (signal.emit)
       │
       ├──▶ L3 MonitorBus (kernel.* / network.* / service.* / task.*)
       │       │
       │       ├──▶ MessageGate (策略过滤: allow/block/mute/hold/redirect)
       │       ├──▶ SSE (API streaming)
       │       └──▶ JSONL (persistence)
       │
       ├──▶ L3 ErrorBus (错误事件 → 指纹去重 → LogService)
       │
       ├──▶ L3 ObservabilityBus (alert/health/metric/audit 汇总)
       │
       └──▶ L3 ReferenceChannel (tool_call / card_lifecycle → SHA-256 → JSONL)
```

### 4.2 消息传递链路

```
  L1 LockBus ──▶ sync.py (Mutex/Semaphore/Barrirer/RWLock)
       │
       └──▶ L3 IpcBus (跨 Cell 消息)
              │
              ├──▶ comm_monitor (通信统计采样)
              │
              └──▶ L3B (跨 Cell 协调)
                     │
                     ├──▶ L3BBus (composite 间消息路由)
                     │       │
                     │       └──▶ L3BMessagePool (hot ring + SQLite)
                     │
                     ├──▶ HTN-A (意图分解 → Cell 分片)
                     │
                     └──▶ HTN-B (跨 Cell 路由分解)
```

### 4.3 组件生命周期链路

```
  SystemBus.register(c) → install() → start_all()
       │
       ├──▶ component.bus_init(bus)
       ├──▶ component.bus_start()
       ├──▶ emit(event) → emit_downward
       └──▶ component.bus_stop()
```

---

## 5. 数据流交叉分析

### 5.1 从 emit 到持久化的完整链路

以 card 完成事件为例：

```
  CardRegistry.complete()                                    L3 cell/card
       │
       ▼
  L1 EventBus.emit(SIGNAL_CARD_COMPLETE)                    L1 kernel/event
       │
       ├──▶ MonitorBus.emit(MonitorEvent)                   L3 bus/monitor_bus
       │       ├──▶ JSONL append (同步)
       │       ├──▶ ring buffer
       │       └──▶ SSE callbacks
       │
       ├──▶ MessageGate.evaluate(MonitorEvent)              L3 bus/message_gate
       │       └──▶ rules → allow/block/mute/hold
       │
       ├──▶ ReferenceChannel.card_lifecycle()               L3 bus/reference_channel
       │       └──▶ ring buffer → daemon flush → JSONL
       │
       ├──▶ TaskBus.dispatch(card_id, state)                L3 bus/task_bus
       │       └──▶ subscriber filters → background POST → webhook
       │
       ├──▶ ErrorBus.capture() (if error)                   L3 error_bus
       │
       └──▶ ObservabilityBus.observe("metric")              L3 bus/observability_bus
               └──▶ counter + audit
```

### 5.2 从 Intent 到执行的跨 Cell 链路

```
  L2 Shell: /card "develop feature"                          L2 l2_shell
       │
       ▼
  L3 Cell: execute_card(intent)                              L3 cell/__init__
       │
       ▼
  HTN-A.decompose(intent) → [{cell-1: design,                L3 bus/htn_a
                               cell-2: implement,
                               cell-3: verify}]
       │
       ▼
  各 L3BComposite.route_subtask()                             L3 bus/l3b
       │
       ├──▶ HTN-B.decompose(route, prev_summary)             L3 bus/htn_b
       │       ├──▶ L2 cache search (prev_cell)
       │       └──▶ dispatch_to_next (next_cell)
       │
       ├──▶ L3BBus.send(sender, target, CARD_FORWARD)        L3 bus/l3b_bus
       │       └──▶ L3BMessagePool.push()                    L3 bus/l3b_message_pool
       │
       └──▶ IpcBus.send_task(agent_id, task_data)             L3 bus/ipc
               └──▶ target cell agent
```

### 5.3 数据一致性保证对比

| 总线 | 送达保证 | 持久化 | 去重 | 反压 |
|------|---------|--------|------|------|
| EventBus | 至少一次（异步 dispatch 错误仅日志） | 无 | 无 | 无（回调阻塞 emitter） |
| MonitorBus | 至少一次 | JSONL 同步 | 无 | 无 |
| ErrorBus | 至少一次 | 有（指纹窗口内去重） | 有（指纹去重+5s窗口） | 无 |
| TaskBus | 最多3次重试 | 无 | 无（过滤匹配） | 无 |
| ReferenceChannel | 至少一次（flush 失败重入队列） | JSONL（后台flush） | SHA-256 哈希 | 无（flusher 独立线程） |
| L3BMessagePool | 至少一次 | Hot Ring + SQLite persist | 无 | 有（BACKPRESSURE） |
| LockBus | 精确一次 | 无 | LockMessage.id | 无 |

### 5.4 并发安全对比

| 总线 | 锁类型 | 单例保护 | 说明 |
|------|--------|---------|------|
| L1 EventBus | `RLock` | 模块级变量 | ✅ |
| L1 SystemBus | `Lock` | `get_root_bus()` | ✅ |
| L1 LockBus | `Lock` x2 | DCLP (`_lock_bus_lock`) | ✅ |
| L3 MonitorBus | `RLock` | `get_bus()` | ✅ |
| L3 IpcBus | `RLock` | `get_bus()` | ✅ |
| L3 L3BBus | `Lock` | 无 DCLP | ❌ |
| L3 L3BMessagePool | `Lock` | 实例级 | ✅ |
| L3 HTNPlanner | `RLock` | 实例级 | ✅ |
| L3 ReferenceChannel | `Lock` | DCLP (`_rc_lock`) | ✅ |
| L3 ErrorBus | `Lock` + `RLock` | `get_bus()` | ✅ |

---

## 6. 关键发现与建议

### 6.1 整体评价

总线层设计清晰，20 个总线各有明确职责分工。L1 三大总线提供底层通信基础，L3 总线在 L1 之上建立监控、协调、数据采集的分层体系。

### 6.2 🟡 发现：`L3BBus.get_bus()` 无 DCLP（已修复 🔧）

> 🔧 **已于 2026-07-30 修复**：添加 `_bus_lock = threading.Lock()` + 双重检查锁。

```python
# 修复前
_bus: L3BBus | None = None

def get_bus() -> L3BBus:
    global _bus
    if _bus is None:
        _bus = L3BBus()
    return _bus
```

```python
# 修复后
_bus: L3BBus | None = None
_bus_lock = threading.Lock()

def get_bus() -> L3BBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = L3BBus()
    return _bus
```

### 6.3 🟡 发现：MonitorBus emit 同步路径含 IO（已修复 🔧）

> 🔧 **已于 2026-07-30 修复**：JSONL 持久化和 SSE callbacks 通过 `ThreadPoolExecutor(max_workers=2)` 异步化，emit 路径上仅保留 O(1) ring buffer append。

原 `emit()` 中：
1. JSONL 写入 → 改为 `self._executor.submit(self._append_persist, event)`
2. SSE callbacks → 改为 `self._executor.submit(self._safe_sse, cb, event)`

### 6.4 🟡 发现：ObservabilityBus 8 处 `except Exception`（已修复 🔧）

> 🔧 **已于 2026-07-30 修复**：全部替换为 `(ImportError, AttributeError)`，_metric 额外加 `KeyError`。

### 6.5 🟢 亮点：L3BMessagePool 的两级缓存 + 反压

Hot Ring + SQLite persist + BACKPRESSURE 的设计是总线中唯一有明确反压机制的模块。`_should_backpressure()` 检查 backlog + cooldown。

### 6.6 🟢 亮点：ReferenceChannel 的 fail-safe flush

```
flush 失败时:
  with self._lock:
      self._ring.extendleft(reversed(lines))  # 重入队列
```

即使磁盘写入失败，数据也不会丢失——重新入队等待下一次 flush。

### 6.7 🟢 亮点：HTN 三层分解体系

HTN-A / HTN-B / HTN-C 构成了清晰的三层任务分解链路：全局意图 → 跨 Cell 路由 → 细胞内执行。与 L3B 链式拓扑配合，实现跨 Cell 无障碍扩展。

### 6.8 改进建议汇总

| 优先级 | 问题 | 影响 | 建议 |
|--------|------|------|------|
| P2 | L3BBus 单例无 DCLP | 并发安全 | 添加 `_bus_lock` |
| P2 | MonitorBus emit 同步 I/O | 可能阻塞 emitter | JSONL 异步化 |
| P2 | ObservabilityBus 4 处 `except Exception` | 错误掩盖 | 精确异常类型 |
| P3 | EventBus history `[-limit*2:]` | 无文档的 magic factor | 提取为 EVT_QUERY_SLICE_MULTI 常量 |
| P3 | ErrorBus 726 行过大 | 可维护性 | 拆分 error()/warn()/critical() 模板方法 |
