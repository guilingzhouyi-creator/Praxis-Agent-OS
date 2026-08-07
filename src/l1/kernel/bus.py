"""SystemBus — unified component lifecycle, topology, and health aggregation.

NOT a message transport layer.  Existing transport buses (EventBus, IpcBus,
L3BBus, LockBus) remain independent.  SystemBus sits ABOVE them:
  - Registers all Components across all layers
  - Resolves dependency topology (depends_on → topological sort)
  - Manages lifecycle (install → init → start → stop)
  - Aggregates health/stats (recursive across sub-buses)
  - Exposes topology as a queryable tree

Usage:
  from l1.kernel.bus import SystemBus, Component, ComponentMeta

  class MyComponent(Component):
      meta = ComponentMeta(name="my", depends_on=["pmu"])
      def bus_init(self, bus): ...
      def bus_start(self): ...
      def bus_stop(self): ...

  bus = SystemBus()
  bus.register(MyComponent(...))
  bus.register(OtherComponent(...))
  bus.install()     # topological sort + bus_init
  bus.start_all()
  bus.health()
  bus.stop_all()
"""

from __future__ import annotations

import logging
import threading
from abc import ABC
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# 1. Component protocol
# ════════════════════════════════════════════════════════════════


@dataclass
class ComponentMeta:
    """Declarative component metadata — defined as a class variable on each Component subclass."""
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    optional_deps: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class Component(ABC):
    """Base class for all bus-managed components.

    Subclasses MUST define:
      meta = ComponentMeta(name="...", depends_on=[...])

    May override:
      bus_init(bus)   — register event listeners, obtain dep references
      bus_start()     — start background threads / connections
      bus_stop()      — graceful shutdown
      bus_health()    — return status dict
      bus_stats()     — return metric dict (consumed by StatsCenter)
    """

    meta: ComponentMeta = ComponentMeta()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.meta.name and cls.__name__ != "Component":
            cls.meta.name = cls.__name__.lower().replace("component", "")

    def bus_init(self, bus: SystemBus) -> None:
        """Lifecycle hook: initialize dependencies and register listeners."""
        pass

    def bus_start(self) -> None:
        """Lifecycle hook: start background threads or connections."""
        pass

    def bus_stop(self) -> None:
        """Lifecycle hook: stop background work gracefully."""
        pass

    def bus_health(self) -> dict:
        """Return component health status dict."""
        return {"status": "ok"}

    def bus_stats(self) -> dict:
        """Return component metric dict."""
        return {}


# ════════════════════════════════════════════════════════════════
# 2. SystemBus — component registry + lifecycle + topology + health
# ════════════════════════════════════════════════════════════════


class SystemBus:
    """Unified component bus — registration, dependency resolution,
    lifecycle management, health/stats aggregation, event routing.

    Architecture:
      RootBus → [child buses: kernel, cell-*, composite-*, global, bridge]
      Each child bus holds its own components.
      emit() bubbles up to parent and broadcasts to siblings.
    """

    def __init__(self, parent: SystemBus | None = None, name: str = ""):
        self.parent = parent
        self.name = name or str(id(self))
        self.children: dict[str, SystemBus] = {}
        self._components: dict[str, Component] = {}
        self._state: dict[str, str] = {}          # comp_name → lifecycle state
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.RLock()
        self._wired = False

    # ── 1. Registration ────────────────────────────────────────

    def register(self, component: Component) -> SystemBus:
        """Register a component instance into this bus."""
        name = component.meta.name
        if not name:
            raise ValueError(f"Component {type(component).__name__} has empty meta.name")
        with self._lock:
            if name in self._components:
                logger.warning("bus %s: component %s already registered — overwriting", self.name, name)
            self._components[name] = component
            self._state[name] = "registered"
            logger.debug("bus %s: registered %s", self.name, name)
        return self

    def get(self, name: str, visited: set[int] | None = None) -> Component | None:
        """Recursive lookup: local → parent → children.

        Uses ``visited`` set (bus id's) to prevent infinite loops.
        """
        if visited is None:
            visited = set()
        bus_id = id(self)
        if bus_id in visited:
            return None
        visited.add(bus_id)

        with self._lock:
            if name in self._components:
                return self._components[name]

        if self.parent:
            result = self.parent.get(name, visited)
            if result:
                return result

        for child in self.children.values():
            if id(child) in visited:
                continue
            result = child.get(name, visited)
            if result:
                return result
        return None

    def list_components(self, tag: str = "") -> list[Component]:
        """List all components, optionally filtered by tag."""
        with self._lock:
            comps = list(self._components.values())
        if tag:
            comps = [c for c in comps if tag in c.meta.tags]
        return comps

    # ── 2. Sub-bus management (mount/unmount) ──────────────────

    def mount(self, name: str) -> SystemBus:
        """Create and attach a child sub-bus.  Redundant mount returns existing."""
        with self._lock:
            if name in self.children:
                return self.children[name]
            child = SystemBus(parent=self, name=name)
            self.children[name] = child
            logger.info("bus %s: mounted child %s", self.name, name)
            return child
        return None  # unreachable

    def unmount(self, name: str) -> None:
        """Detach and stop a child sub-bus."""
        with self._lock:
            child = self.children.pop(name, None)
        if child:
            child.stop_all()
            logger.info("bus %s: unmounted child %s", self.name, name)

    # ── 3. Lifecycle: install → init → start → stop ──────────

    def install(self) -> SystemBus:
        """Resolve dependency order → call bus_init() on each component.

        Uses topological sort on depends_on.  Circular deps raise ValueError.
        """
        with self._lock:
            if self._wired:
                logger.warning("bus %s: already installed", self.name)
                return self
            names = list(self._components.keys())
            sorted_names = _topological_sort(names, self._dep_graph(names))
            for n in sorted_names:
                comp = self._components[n]
                try:
                    comp.bus_init(self)
                    self._state[n] = "inited"
                except Exception as e:
                    self._state[n] = f"init_error: {e}"
                    logger.error("bus %s: component %s init failed: %s", self.name, n, e)
                    raise
            self._wired = True
            logger.info("bus %s: installed %d components", self.name, len(sorted_names))
        # Recursively install children
        for child in self.children.values():
            child.install()
        return self

    def start_all(self) -> dict:
        """Start all components (inited → started). Returns {name: success|error}."""
        results: dict[str, str] = {}
        with self._lock:
            for name, comp in self._components.items():
                if self._state.get(name) != "inited":
                    results[name] = f"skip: {self._state.get(name, 'unknown')}"
                    continue
                try:
                    comp.bus_start()
                    self._state[name] = "started"
                    results[name] = "started"
                except Exception as e:
                    self._state[name] = f"start_error: {e}"
                    results[name] = f"error: {e}"
                    logger.error("bus %s: component %s start failed: %s", self.name, name, e)
        # Start children
        for cname, child in self.children.items():
            results[f"bus:{cname}"] = str(child.start_all())
        return results

    def stop_all(self) -> None:
        """Stop all components (reverse order)."""
        with self._lock:
            names = list(self._components.keys())
        # Reverse topological order
        for name in reversed(names):
            comp = self._components.get(name)
            if comp is None:
                continue
            state = self._state.get(name, "")
            if state not in ("started", "inited"):
                continue
            try:
                comp.bus_stop()
                self._state[name] = "stopped"
            except Exception as e:
                logger.warning("bus %s: component %s stop: %s", self.name, name, e)
        for child in self.children.values():
            child.stop_all()

    # ── 4. Event routing ───────────────────────────────────────

    def emit(self, event: str, data: Any = None, source: str = "") -> None:
        """Emit an event.  Always propagates from root downward to ALL buses,
        ensuring every handler in every bus sees the event.  The source
        parameter indicates which bus originated the emission.

        If this is a child bus, delegates to root for full-tree broadcast.
        """
        if self.parent:
            self.parent.emit(event, data, source or self.name)
            return
        with self._lock:
            self._run_handlers(event, data, source)
            for child in list(self.children.values()):
                child._emit_downward(event, data, source)

    def _emit_downward(self, event: str, data: Any, source: str) -> None:
        """Recursive downward dispatch (used by root broadcast)."""
        self._run_handlers(event, data, source)
        for child in list(self.children.values()):
            child._emit_downward(event, data, source)

    def _run_handlers(self, event: str, data: Any, source: str) -> None:
        """Run matching handlers for this bus only."""
        handlers = list(self._handlers.get(event, []))
        for pattern, hlist in list(self._handlers.items()):
            if pattern != event and _wildcard_match(pattern, event):
                handlers.extend(hlist)
        for h in handlers:
            try:
                h({"event": event, "data": data, "source": source, "bus": self.name})
            except Exception as e:
                logger.warning("bus %s: handler for %s failed: %s", self.name, event, e)

    def on(self, event: str, handler: Callable) -> None:
        """Register an event handler.  Supports wildcards:
        "watchdog.*" matches "watchdog.crash", "watchdog.pet", etc.
        """
        with self._lock:
            self._handlers[event].append(handler)

    # ── 5. Health & stats aggregation ──────────────────────────

    def health(self) -> dict:
        """Recursive health: returns tree of {component: {status, ...}}."""
        result: dict[str, Any] = {"bus": self.name}
        with self._lock:
            for name, comp in self._components.items():
                try:
                    result[name] = comp.bus_health()
                except Exception as e:
                    result[name] = {"status": "error", "message": str(e)}
        for cname, child in self.children.items():
            result[f"bus:{cname}"] = child.health()
        return result

    def stats(self) -> dict:
        """Recursive stats: flat dict of {bus.component.key: value}."""
        result: dict[str, Any] = {}
        with self._lock:
            for name, comp in self._components.items():
                try:
                    for k, v in comp.bus_stats().items():
                        result[f"{self.name}.{name}.{k}"] = v
                except Exception:
                    logger.debug("bus: failed to collect stats from %s", name)
        for cname, child in self.children.items():
            for k, v in child.stats().items():
                result[f"{self.name}.bus:{cname}.{k}"] = v
        return result

    def state_map(self) -> dict[str, str]:
        """Return all component lifecycle states."""
        result: dict[str, str] = {}
        with self._lock:
            for n, s in self._state.items():
                result[f"{self.name}.{n}"] = s
        for cname, child in self.children.items():
            for k, v in child.state_map().items():
                result[f"{self.name}.bus:{cname}.{k}"] = v
        return result

    # ── 6. Internal ────────────────────────────────────────────

    def _dep_graph(self, names: list[str]) -> dict[str, list[str]]:
        """Build dependency graph from ComponentMeta.depends_on."""
        graph: dict[str, list[str]] = {}
        for n in names:
            comp = self._components[n]
            deps = []
            for dep in comp.meta.depends_on:
                if dep in self._components or (self.parent and self.parent.get(dep)):
                    deps.append(dep)
            for dep in comp.meta.optional_deps:
                if dep in self._components or (self.parent and self.parent.get(dep)):
                    deps.append(dep)
            graph[n] = deps
        return graph


# ════════════════════════════════════════════════════════════════
# 3. Topological sort
# ════════════════════════════════════════════════════════════════


def _topological_sort(names: list[str], graph: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm.  Raises ValueError if cycle detected."""
    in_degree = {n: 0 for n in names}
    for n in names:
        for dep in graph.get(n, []):
            if dep in in_degree:
                in_degree[n] = in_degree.get(n, 0) + 1

    queue = [n for n in names if in_degree.get(n, 0) == 0]
    result: list[str] = []
    while queue:
        n = queue.pop(0)
        result.append(n)
        for m in names:
            if n in graph.get(m, []):
                in_degree[m] -= 1
                if in_degree[m] == 0:
                    queue.append(m)
    if len(result) != len(names):
        cycle = set(names) - set(result)
        raise ValueError(f"Circular dependency detected among: {cycle}")
    return result


def _wildcard_match(pattern: str, event: str) -> bool:
    """Simple wildcard: 'watchdog.*' matches 'watchdog.crash'."""
    if pattern == event:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return event.startswith(prefix + ".") or event == prefix
    return False


# ════════════════════════════════════════════════════════════════
# 4. Global singleton
# ════════════════════════════════════════════════════════════════

_root_bus: SystemBus | None = None
_root_lock = threading.Lock()


def get_root_bus() -> SystemBus:
    """Get or create the root SystemBus singleton."""
    global _root_bus
    if _root_bus is None:
        with _root_lock:
            if _root_bus is None:
                _root_bus = SystemBus(name="root")
    return _root_bus


def reset_root_bus() -> None:
    """Reset the root bus (for testing / shutdown)."""
    global _root_bus
    if _root_bus:
        _root_bus.stop_all()
    _root_bus = None
