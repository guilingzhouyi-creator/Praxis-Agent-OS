# SystemBus — 通用组件总线架构

## 1. 问题

当前 Praxis 组件间的关系是"手工串联"：

```
Cell.__init__ 中 16 步手工构建依赖链
  ├─ 每加一个组件改一遍 __init__
  ├─ 生命周期无统一管理 (谁先 start/stop 靠人脑记)
  ├─ Component -> Component 的直接方法调用 (紧耦合)
  ├─ 部分组件是全局单例 (StatsCenter/RecordCenter)
  ├─ 部分组件是 Cell 实例级 (PMU/Watchdog/ICache/MMU/...)
  └─ 没有统一的消息/事件路由
```

需要一种**通用组件总线架构**，让任意层级/任意生命周期的组件以同一套协议注册、发现、通信、启停。

---

## 2. 架构概览

```
Application
  └─ SystemBus (根总线, 全局唯一)
       │
       ├── 注册表: ComponentMeta → Component 实例
       ├── 消息路由: event → handlers (父子冒泡 + 广播)
       ├── 生命周期: installed → inited → started → stopped
       ├── 健康聚合: health() → 遍历子组件
       └── 指标聚合: stats() → 遍历子组件 → StatsCenter
       │
       ├── [子总线] L1Services
       │    ├── EventBusComponent
       │    ├── GateChainComponent
       │    ├── ConstitutionComponent
       │    └── AllocatorComponent
       │
       ├── [子总线] Cell-1
       │    ├── CellPmuComponent       (publishes: pmu.snapshot)
       │    ├── CellWatchdogComponent   (publishes: watchdog.crash|timeout|pet)
       │    ├── CellICacheComponent     (publishes: icache.hit|miss|evict)
       │    ├── CellMmuComponent        (publishes: tlb.hit|miss|flush)
       │    ├── CellInterruptComponent  (publishes: interrupt.trigger)
       │    └── CellCacheComponent      (publishes: cache.hit|miss|inject|flush)
       │
       ├── [子总线] L4Bridge
       │    ├── ApiGatewayComponent
       │    └── SSEBridgeComponent
       │
       └── [子总线] GlobalServices
            ├── StatsCenterComponent    (listens: *.stats → cross-cell aggregate)
            ├── RecordCenterComponent   (listens: *.error → persist)
            ├── SettingsCenterComponent
            └── MonitorBusComponent     (listens: *.health → alert)
```

---

## 3. 核心类型

### 3.1 ComponentMeta

```python
@dataclass
class ComponentMeta:
    name: str                            # 全局唯一组件名, 如 "pmu", "watchdog"
    version: str = "0.1.0"
    description: str = ""
    depends_on: list[str] = field(default_factory=list)    # 硬依赖 (必先 init)
    optional_deps: list[str] = field(default_factory=list) # 软依赖 (有就用, 无则跳过)
    tags: list[str] = field(default_factory=list)           # 分类标签
```

### 3.2 Component 协议

```python
class Component(ABC):
    """所有总线组件必须实现此接口。"""

    meta: ClassVar[ComponentMeta]   # 类属性, 声明式定义依赖

    def bus_init(self, bus: "SystemBus") -> None:
        """安装阶段: 注册消息监听, 获取依赖引用。

        此时 bus.get(dep) 能获取到所有硬依赖组件。
        组件应在此方法中保存 bus 引用, 并 bus.on() 注册事件监听。
        """

    def bus_start(self) -> None:
        """启动阶段: 启动后台线程, 打开连接, 开始定时任务。"""

    def bus_stop(self) -> None:
        """关闭阶段: 优雅关闭, 释放资源。幂等。"""

    def bus_health(self) -> dict:
        """返回健康状态。默认返回 {"status": "ok"}。"""
        return {"status": "ok"}

    def bus_stats(self) -> dict:
        """返回统计指标字典 (会被 StatsCenter 自动聚合)。"""
        return {}
```

### 3.3 SystemBus

```python
class SystemBus:
    """通用组件总线 — 注册 / 依赖解析 / 生命周期 / 消息路由 / 健康聚合。"""

    def __init__(self, parent: SystemBus | None = None):
        self.parent = parent            # 父总线 (消息气泡)
        self.children: dict[str, SystemBus] = {}
        self._components: dict[str, Component] = {}
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._states: dict[str, str] = {}  # "registered" | "inited" | "started" | "stopped"
        self._inited = False

    # ════════════════════════════════════════════
    # 1. 注册与安装
    # ════════════════════════════════════════════

    def register(self, component: Component) -> Self:
        """注册一个已实例化的组件。"""
        ...

    def install(self) -> Self:
        """拓扑排序 → 按序 bus_init() 每个组件。"""
        ...

    # ════════════════════════════════════════════
    # 2. 子总线 (热插拔)
    # ════════════════════════════════════════════

    def mount(self, name: str, bus: SystemBus | None = None) -> SystemBus:
        """挂载子总线。如不传 bus 则自动新建。"""
        ...

    def unmount(self, name: str) -> None:
        """卸载子总线，自动 stop_all。"""
        ...

    # ════════════════════════════════════════════
    # 3. 生命周期
    # ════════════════════════════════════════════

    def start_all(self) -> dict:
        """启动所有组件 (inited → started)。返回 {name: success|error}。"""
        ...

    def stop_all(self) -> None:
        """停止所有组件 (逆序)。"""
        ...

    # ════════════════════════════════════════════
    # 4. 组件查询
    # ════════════════════════════════════════════

    def get(self, name: str) -> Component | None:
        """递归查找: 本总线 → 父总线 → 子总线。"""
        ...

    def list(self, tag: str = "") -> list[Component]:
        """按标签过滤。"""
        ...

    # ════════════════════════════════════════════
    # 5. 消息路由
    # ════════════════════════════════════════════

    def emit(self, event: str, data: Any = None, source: str = "") -> None:
        """发送消息。传递路径: 本组件 → 本总线 → 子总线 → 父总线。"""
        ...

    def on(self, event: str, handler: Callable) -> None:
        """监听消息。支持通配符: "watchdog.*" 匹配 "watchdog.crash"。"""
        ...

    # ════════════════════════════════════════════
    # 6. 健康与指标
    # ════════════════════════════════════════════

    def health(self) -> dict:
        """聚合所有子组件的 health()。返回树形结构。"""
        ...

    def stats(self) -> dict:
        """聚合所有子组件的 stats()。返回扁平字典 (供 StatsCenter 消费)。"""
        ...
```

---

## 4. 消息路由 (emit/on) 设计

### 4.1 路由规则

```
emit("watchdog.crash", {"agent_id": "agent-a"}, source="cell-1.watchdog")

路径:
  1. cell-1 总线 → cell-1 上所有 on("watchdog.crash") 处理器
  2. cell-1 总线 → cell-1 上所有 on("watchdog.*") 通配符处理器
  3. cell-1 总线 → 子总线 (无)
  4. cell-1 总线 → 冒泡到 SystemBus 根总线
  5. SystemBus → 所有 on("watchdog.crash") 全局处理器
  6. SystemBus → 所有 on("watchdog.*") 通配符处理器
  7. SystemBus → 子总线 (L1Services, L4Bridge, GlobalServices)
```

### 4.2 命名规范

```
{source}.{action}[.{detail}]

例:
  pmu.snapshot            # PMU 产生了快照
  watchdog.crash          # 看门狗检测到 Agent 崩溃
  watchdog.timeout        # 看门狗超时
  watchdog.pet            # Agent 喂狗
  tlb.hit                 # TLB 命中
  tlb.miss                # TLB 未命中 → 页遍历
  tlb.flush               # TLB 冲刷
  interrupt.trigger       # 中断被触发
  cache.hit               # CellCache 命中
  stats.heartbeat         # StatsCenter 定期心跳 (SSE 推流)
```

---

## 5. 生命周期状态机

```
                register()
                    │
                    ▼
              ┌─────────────┐
              │  REGISTERED  │
              └──────┬──────┘
                     │ install() → 拓扑排序 → bus_init()
                     ▼
              ┌─────────────┐
              │   INITED    │
              └──────┬──────┘
                     │ start_all()
                     ▼
              ┌─────────────┐
              │  STARTED    │  ←── 正常运行态
              └──────┬──────┘
                     │ stop_all() / unmount()
                     ▼
              ┌─────────────┐
              │  STOPPED    │  ←── 可重新 register
              └─────────────┘
```

---

## 6. 迁移计划

### Phase 1: 核心 (src/l1/kernel/bus.py)

| 文件 | 内容 |
|---|---|
| `src/l1/kernel/bus.py` | ComponentMeta, Component, SystemBus |

### Phase 2: 组件包装器 (每个现有类一个 wrapper)

| 现有类 | 包装器 | 关键变更 |
|---|---|---|
| CellPmu | CellPmuComponent | `meta.name="pmu"`, `bus_init` 中 bus.on 注册 PMU 监听 |
| CellWatchdog | CellWatchdogComponent | `depends_on=["pmu"]`, 回调改为 bus.emit |
| CellICache | CellICacheComponent | `depends_on=["pmu"]` |
| CellMmu | CellMmuComponent | `depends_on=["tlb","icache"]` |
| CellTlb | CellTlbComponent | `depends_on=["pmu"]` |
| CellInterrupt | CellInterruptComponent | `depends_on=["pmu"]`, 硬编码 handler 改为 bus.on |
| CellCache | CellCacheComponent | `depends_on=["pmu"]` |
| StatsCenter | StatsCenterComponent | `bus.on("*.stats")` 自动聚合 |
| RecordCenter | RecordCenterComponent | `bus.on("*.error")` 自动捕获 |
| SubAgentDispatcher | SubAgentComponent | `depends_on=["cell"]` |

### Phase 3: Cell.__init__ 替换

```python
# 改前: 16 步手工串联
self._pmu = CellPmu(cell_id)
self._watchdog = CellWatchdog(cell_id, pmu=self._pmu)
self._icache = ICache(cell_id, pmu=self._pmu)
...

# 改后: 声明式注册
self.bus = SystemBus(parent=root_bus)
self.bus.register(CellPmuComponent(cell_id))
self.bus.register(CellWatchdogComponent(cell_id))
self.bus.register(CellICacheComponent(cell_id))
...
self.bus.install()
self._pmu = self.bus.get("pmu")
```

### Phase 4: 全局服务迁移

```
StatsCenter → StatsCenterComponent (依赖: MonitorBus)
RecordCenter → RecordCenterComponent (依赖: ErrorBus, LogService, StatsCenter)
SettingsCenter → SettingsCenterComponent (依赖: 无)
```

### Phase 5: 测试

```
tests/test_bus.py:
  ├─ test_register_and_get
  ├─ test_topological_sort
  ├─ test_lifecycle_start_stop
  ├─ test_emit_on_same_bus
  ├─ test_emit_bubble_up
  ├─ test_emit_bubble_down
  ├─ test_wildcard_match
  ├─ test_mount_unmount
  ├─ test_health_aggregation
  └─ test_stats_aggregation
```

---

## 7. 与现有 boot 序列的关系

```python
# boot.py 改造后

def boot(agent_config):
    bus = SystemBus()                     # 创建根总线

    # 1. L1 内核服务
    l1 = bus.mount("kernel")
    l1.register(EventBusComponent())
    l1.register(GateChainComponent())
    l1.register(ConstitutionComponent())
    l1.register(AllocatorComponent())

    # 2. 全局服务
    gs = bus.mount("global")
    gs.register(StatsCenterComponent())
    gs.register(MonitorBusComponent())
    gs.register(RecordCenterComponent())

    # 3. Cell
    cb = bus.mount(f"cell-{cell_id}")
    cb.register(CellPmuComponent(cell_id))
    cb.register(CellWatchdogComponent(cell_id))
    ...

    # 4. 一键生命周期
    bus.install()      # 拓扑排序 + bus_init
    bus.start_all()    # 全部启动
    # 正常运作...

    bus.stop_all()     # 关闭
```

---

## 8. 向后兼容

| 旧用法 | 新用法 | 过渡期 |
|---|---|---|
| `from l3.cell_pmu import CellPmu` | `from l3.bus.components import CellPmuComponent` | 旧类保留，新组件包装 |
| `self._pmu.increment(...)` | `self.bus.get("pmu").increment(...)` | bus.get("pmu") 返回原实例 |
| `get_center().ingest(...)` | `bus.emit("pmu.snapshot", ...)` | 两种方式同时支持 |
| `cell.stats()` | `bus.stats()` | bus 自动聚合 |
