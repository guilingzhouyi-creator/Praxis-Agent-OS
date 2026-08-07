"""Registry base — unified declarative registration architecture.

Provides the base types and protocols for all registration systems:
  - RegisterableSpec: generic spec dataclass for any registrable entity
  - Registry: ABC interface for all registries
  - MapRegistry: concrete dict-backed implementation

Design:
  - RegisterableSpec is a generic container. Each domain (commands, tools,
    subagents, plugins) can extend it with domain-specific fields.
  - Registry defines the common interface. MapRegistry provides the
    default implementation using a thread-safe dict.
  - All registries share: register/unregister/get/list/stats
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from l1.kernel.params.system import LOG_TRUNC_200

T = TypeVar("T", bound="RegisterableSpec")


# ── Base spec for any registrable entity ──


@dataclass
class RegisterableSpec:
    """Generic spec for any registrable entity.

    Domain-specific registries (commands, tools, subagents, plugins)
    can subclass this and add domain-specific fields.

    Fields:
        name: Unique identifier within the registry.
        handler: Callable that implements the action.
        description: Human-readable description.
        category: Grouping key (e.g. "files", "network", "session").
        tags: Arbitrary tags for filtering.
        metadata: Arbitrary key-value store.
        version: Semantic version of this spec.
    """
    name: str
    handler: Callable | None = None
    description: str = ""
    category: str = "other"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the spec to a plain dict (description truncated)."""
        return {
            "name": self.name,
            "description": self.description[:LOG_TRUNC_200],
            "category": self.category,
            "tags": list(self.tags),
            "version": self.version,
        }


# ── Registry interface ──


class Registry(ABC, Generic[T]):
    """Abstract registry interface.

    All registries (commands, tools, subagents, plugins) implement this.
    """

    @abstractmethod
    def register(self, spec: T, *, source: str = "code") -> bool:
        """Register a spec. Returns True on success, False if already exists."""
        ...

    @abstractmethod
    def unregister(self, name: str) -> bool:
        """Remove a registered spec by name. Returns True if removed."""
        ...

    @abstractmethod
    def get(self, name: str) -> T | None:
        """Retrieve a registered spec by name."""
        ...

    @abstractmethod
    def list(self, category: str = "") -> list[T]:
        """List all registered specs, optionally filtered by category."""
        ...

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """Return registry statistics."""
        ...


# ── Concrete registry implementation ──


class MapRegistry(Registry[T]):
    """Thread-safe dict-backed registry.

    Example:
        spec = RegisterableSpec(name="my-tool", handler=my_fn, category="utils")
        reg = MapRegistry[RegisterableSpec]()
        reg.register(spec)
        assert reg.get("my-tool") is spec

    Extensions:
      - on_register(name, spec)  — called after each successful registration
      - on_unregister(name)      — called after each successful unregistration
      Both accept a Callable[[str, T | None], None] signature.
    """

    def __init__(self, allow_overwrite: bool = False):
        self._items: dict[str, T] = {}
        self._lock = threading.RLock()
        self._allow_overwrite = allow_overwrite
        self._stats: dict[str, int] = {"registers": 0, "unregisters": 0}
        self._on_register: Callable[[str, T], None] | None = None
        self._on_unregister: Callable[[str], None] | None = None

    def set_on_register(self, cb: Callable[[str, T], None]) -> None:
        """Set a callback invoked after each successful registration."""
        self._on_register = cb

    def set_on_unregister(self, cb: Callable[[str], None]) -> None:
        """Set a callback invoked after each successful unregistration."""
        self._on_unregister = cb

    def register(self, spec: T, *, source: str = "code") -> bool:
        """Register *spec*; returns False if the name exists and overwrite is disallowed."""
        with self._lock:
            if spec.name in self._items and not self._allow_overwrite:
                return False
            self._items[spec.name] = spec
            self._stats["registers"] += 1
            cb = self._on_register
        if cb:
            cb(spec.name, spec)
        return True

    def unregister(self, name: str) -> bool:
        """Remove *name* from the registry; returns True if it was present."""
        with self._lock:
            if name not in self._items:
                return False
            del self._items[name]
            self._stats["unregisters"] += 1
            cb = self._on_unregister
        if cb:
            cb(name)
        return True

    def get(self, name: str) -> T | None:
        """Return the spec registered under *name*, or None."""
        with self._lock:
            return self._items.get(name)

    def list_items(self, category: str = "") -> list[T]:
        """Return all registered specs, optionally filtered by *category*."""
        with self._lock:
            if not category:
                return list(self._items.values())
            return [s for s in self._items.values() if s.category == category]

    def list(self, category: str = "") -> list[T]:
        """Return all registered specs, optionally filtered by *category*.

        Compatibility alias of :meth:`list_items` — the Registry ABC requires
        ``list`` and legacy callers (tests, ToolRegistry) depend on it.
        """
        return self.list_items(category=category)

    def all_names(self) -> list[str]:
        """Return the names of all registered specs."""
        with self._lock:
            return list(self._items.keys())

    def stats(self) -> dict[str, Any]:
        """Return registry statistics (total, register/unregister counts, categories)."""
        with self._lock:
            return {
                "total": len(self._items),
                **self._stats,
                "categories": self._count_by_category(),
            }

    def _count_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self._items.values():
            counts[s.category] = counts.get(s.category, 0) + 1
        return counts

    def clear(self) -> int:
        """Remove all entries; returns the number of entries cleared."""
        with self._lock:
            n = len(self._items)
            self._items.clear()
            return n
