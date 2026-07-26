"""Ports — pure abstract interfaces for hexagonal architecture.

All cross-platform, cross-language boundary definitions live here.
No concrete implementation, no socket/threading/os/json imports.
Kernel domain code depends only on these ports.
Adapters (in services/adapters/) implement them.

Current ports:
  TransportPort  — send bytes to peers, receive messages via callback
  ChannelPort    — message channel with backpressure (producer/consumer)
  EventBusPort   — event publish/subscribe
  WorkerPort     — abstract concurrency (thread / asyncio / process)
  I18nPort       — internationalization lookup

Usage:
  from kernel.ports import TransportPort, Message, Endpoint
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


# ── Shared value types ──────────────────────────────────────────────────────


@dataclass
class Endpoint:
    """Transport endpoint — abstract address, not tied to TCP (host, port).

    Examples:
      Endpoint("10.0.0.2:42070", hint="tcp")
      Endpoint("wss://hub.praxis.io/node-1", hint="ws")
      Endpoint("\\\\.\\pipe\\praxis-cell-1", hint="pipe")  # Windows named pipe
    """
    address: str = ""
    hint: str = "tcp"       # transport_hint — lets adapter choose wire protocol


@dataclass
class Result:
    """Generic success/failure result — no exception leak across port boundaries."""
    success: bool = True
    error: str = ""
    data: dict = field(default_factory=dict)

    @staticmethod
    def ok(**data: Any) -> Result:
        return Result(success=True, data=data)

    @staticmethod
    def fail(msg: str, **data: Any) -> Result:
        return Result(success=False, error=msg, data=data)


@dataclass
class Message:
    """Domain message — locale-aware, adapter-neutral serialization.

    Adapters choose the wire format (JSON / MsgPack / Protobuf).
    """
    type: str = "message"
    source: str = ""
    target: str = ""
    payload: Any = None
    timestamp: float = 0.0
    locale: str = "en"                  # sender locale — receiver may localize reply
    headers: dict = field(default_factory=dict)


@dataclass
class Event:
    """Domain event — carry pre-localized message for multi-lingual consumers."""
    type: str = ""                      # "network.peer.join" | "network.peer.loss"
    source: str = ""
    severity: str = "info"              # "info" | "warn" | "crit"
    message: str = ""                   # English default
    message_locale: str = ""            # Localized variant (e.g. zh-CN)
    data: dict = field(default_factory=dict)


# ── TransportPort ────────────────────────────────────────────────────────────


class TransportPort(ABC):
    """Transmit bytes to remote endpoints; receive messages via handler callback.

    Cross-platform contract:
      - start/stop   MUST be idempotent and re-entrant
      - send(target, data) MUST NOT block the caller for I/O wait
        (actual I/O happens on transport's own threads)
      - register_handler  MUST be thread-safe
    """
    name: str = "abstract.transport"

    @abstractmethod
    def start(self, node_id: str, config: Any) -> Result:
        """Start listener and discovery. Returns bound endpoint info."""
        ...

    @abstractmethod
    def stop(self) -> Result:
        """Stop listener, close sockets, release resources."""
        ...

    @abstractmethod
    def send(self, target: Endpoint, data: bytes) -> Result:
        """Send raw bytes to a remote endpoint. Non-blocking contract."""
        ...

    @abstractmethod
    def register_handler(self, msg_type: str, handler: Callable) -> None:
        """Register a callback for incoming messages of *msg_type*."""
        ...


# ── ChannelPort ──────────────────────────────────────────────────────────────


class ChannelPort(ABC):
    """Message channel — decouples producer from consumer, with backpressure.

    Cross-platform contract:
      - put(item) when full: blocks up to *timeout* or returns False
      - get() when empty: blocks up to *timeout* or returns None
      - All operations MUST be thread-safe.
    """
    @abstractmethod
    def put(self, item: Any, timeout: float | None = None) -> bool:
        """Enqueue an item. Returns False if full and *timeout* elapsed."""
        ...

    @abstractmethod
    def get(self, timeout: float | None = None) -> Any | None:
        """Dequeue an item. Returns None if empty and *timeout* elapsed."""
        ...

    @abstractmethod
    def size(self) -> int:
        """Current number of items in the channel."""
        ...

    @abstractmethod
    def capacity(self) -> int:
        """Maximum capacity (0 = unbounded)."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the channel; subsequent put/get raise or return sentinel."""
        ...


# ── EventBusPort ─────────────────────────────────────────────────────────────


class EventBusPort(ABC):
    """Publish/subscribe event bus — decouples event producers from consumers.

    Cross-platform contract:
      - emit(event) MUST be non-blocking
      - subscribe(handler) returns a subscription ID for unsubscribe
      - subscribe with pattern=None subscribes to ALL event types
    """
    @abstractmethod
    def emit(self, event: Event) -> None:
        """Publish an event to all matching subscribers."""
        ...

    @abstractmethod
    def subscribe(self, handler: Callable | None = None,
                  pattern: str | None = None) -> str:
        """Subscribe *handler* to events matching *pattern* (glob). Returns sub_id."""
        ...

    @abstractmethod
    def unsubscribe(self, sub_id: str) -> bool:
        """Remove a subscription by ID."""
        ...

    @abstractmethod
    def stats(self) -> dict:
        """Return subscriber count / event count / etc."""
        ...


# ── WorkerPort ───────────────────────────────────────────────────────────────


class WorkerPort(ABC):
    """Abstract concurrency executor — decouples task submission from execution.

    Cross-platform contract:
      - submit(fn, ...) MUST return a Result (not a raw thread/future)
        so the caller never depends on threading.Thread or asyncio.Task
      - shutdown() MUST wait for running tasks up to *timeout* seconds
    """
    @abstractmethod
    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Result:
        """Submit a callable for execution. Result.success indicates accepted."""
        ...

    @abstractmethod
    def shutdown(self, wait: bool = True, timeout: float | None = None) -> Result:
        """Shut down the worker pool, optionally waiting for running tasks."""
        ...

    @abstractmethod
    def stats(self) -> dict:
        """Return pool_size / active / queued / completed / rejected."""
        ...


# ── I18nPort ─────────────────────────────────────────────────────────────────


class I18nPort(ABC):
    """Internationalization port — key-based translation lookup.

    Cross-platform contract:
      - t(key) returns the key itself when no translation found (graceful fallback)
      - t(key, **kwargs) supports {variable} substitution in translated strings
      - set_locale(locale) is idempotent; unknown locale falls back to "en"
      - All operations MUST be thread-safe
    """
    @abstractmethod
    def t(self, key: str, **kwargs: Any) -> str:
        """Translate *key* in the current locale with optional variable substitution."""
        ...

    @abstractmethod
    def set_locale(self, locale: str) -> None:
        """Switch active locale."""
        ...

    @abstractmethod
    def get_locale(self) -> str:
        """Return current locale code (e.g. 'en', 'zh-CN')."""
        ...

    @abstractmethod
    def get_available(self) -> list[str]:
        """Return all available locale codes."""
        ...

    @abstractmethod
    def register(self, locale: str, data: dict[str, str | dict]) -> None:
        """Register flat or nested translation data for a locale."""
        ...

    @abstractmethod
    def register_file(self, locale: str, path: str) -> bool:
        """Load translations from a file (YAML/JSON). Returns True on success."""
        ...


# ── CardRegistryPort ─────────────────────────────────────────────────────────


class CardRegistryPort(ABC):
    """Card type registry — query and install card definitions.

    Replaces lazy ``from services.card_unified import list_card_types``
    and ``from services.card_pool import get_pool`` in kernel layer.
    """
    @abstractmethod
    def list_types(self) -> list[dict]:
        """Return all registered card type definitions."""
        ...

    @abstractmethod
    def install_def(self, cdef: dict, source: str = "") -> bool:
        """Install a card definition from a remote peer or file."""
        ...


# ── MonitorBusPort ───────────────────────────────────────────────────────────


class MonitorBusPort(ABC):
    """Monitoring event bus — structured event emission and query.

    Replaces lazy ``from services.monitor_bus import MonitorEvent, get_bus``
    in kernel layer.

    This is a lighter-weight sibling of EventBusPort focused on
    observability events (network status, cell health, agent lifecycle).
    """
    @abstractmethod
    def emit(self, type_: str, source: str, severity: str,
             message: str, data: dict | None = None) -> None:
        """Emit a structured monitoring event."""
        ...

    @abstractmethod
    def query(self, type_prefix: str = "", severity: str = "",
              source: str = "", since: float = 0.0,
              limit: int = 100) -> list[dict]:
        """Query recent events with optional filters."""
        ...


# ── Registry (port → adapter mapping, wired at boot) ─────────────────────────


_PORTS: dict[str, object] = {}


def register_port(name: str, adapter: object) -> None:
    """Register a port adapter at boot time.

    Usage:
      from kernel.ports import register_port
      from services.adapters.i18n_yaml import YamlI18nAdapter

      register_port("i18n", YamlI18nAdapter(locale_dir="./locales"))
    """
    _PORTS[name] = adapter


def get_port(name: str) -> object:
    """Retrieve a registered port adapter by name.

    Raises KeyError if not registered (fail-fast at boot).
    """
    if name not in _PORTS:
        raise KeyError(f"port '{name}' not registered — call register_port() first")
    return _PORTS[name]


def reset_ports() -> None:
    """Clear port registry (for testing / hot-reload)."""
    _PORTS.clear()
