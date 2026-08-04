"""Device manager — abstract device model for external services.

Agents use devices to interact with external backends:
  - LLM providers (Claude, GPT, local)
  - Databases (Postgres, SQLite, Redis)
  - Network services (HTTP APIs, WebSocket)

Each device has a type, rate limit, health status.
The kernel tracks all registered devices and their current health.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from .params.api import DEVICE_RATE_LIMIT_LLM
from .params.kernel import (
    DEVICE_DEGRADED_THRESHOLD,
    DEVICE_DOWN_THRESHOLD,
    DEVICE_HEALTH_INTERVAL,
    DEVICE_MIN_CALLS_DEGRADED,
    DEVICE_MIN_CALLS_DOWN,
)

logger = logging.getLogger(__name__)


class DeviceType(Enum):
    """DeviceType — enum of device type variants."""
    LLM = auto()
    DATABASE = auto()
    NETWORK = auto()
    STORAGE = auto()
    CUSTOM = auto()


# Extensible device type registry — register custom types by name
_DEVICE_TYPE_REGISTRY: dict[str, DeviceType] = {}


def register_device_type(name: str) -> DeviceType:
    """Register a custom device type.  Returns a new DeviceType member.

    Usage::

        MY_TYPE = register_device_type("MY_TYPE")
        dm.register("my-svc", MY_TYPE)
    """
    if name in _DEVICE_TYPE_REGISTRY:
        return _DEVICE_TYPE_REGISTRY[name]
    if hasattr(DeviceType, name):
        raise ValueError(f"DeviceType.{name} already exists as a built-in member")
    # Dynamically extend the enum (Python 3.11+)
    count = max(m.value for m in DeviceType) + 1 if DeviceType.__members__ else 1
    new_member = object.__new__(DeviceType)
    new_member._name_ = name
    new_member._value_ = count
    DeviceType._member_map_[name] = new_member
    _DEVICE_TYPE_REGISTRY[name] = new_member
    return new_member


class DeviceHealth(Enum):
    """DeviceHealth — enum of device health variants."""
    HEALTHY = auto()
    DEGRADED = auto()
    DOWN = auto()


@dataclass
class DeviceCapability:
    """DeviceCapability — device capability record (name, description)."""
    name: str
    description: str = ""


@dataclass
class Device:
    """Device — device record (name, device_type, health, rate_limit, rate_window)."""
    name: str
    device_type: DeviceType
    health: DeviceHealth = DeviceHealth.HEALTHY
    rate_limit: int = DEVICE_RATE_LIMIT_LLM
    rate_window: float = 1.0
    description: str = ""
    capabilities: list[DeviceCapability] = field(default_factory=list)
    connected_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    call_count: int = 0
    error_count: int = 0
    version: str = ""


_CAPABILITY_REGISTRY: dict[DeviceType, list[DeviceCapability]] = {
    DeviceType.LLM: [
        DeviceCapability("text-generation", "Generate text from prompt"),
        DeviceCapability("code-analysis", "Analyze source code"),
        DeviceCapability("summarization", "Summarize findings"),
    ],
    DeviceType.DATABASE: [
        DeviceCapability("query", "Execute read queries"),
        DeviceCapability("write", "Execute write queries"),
        DeviceCapability("migrate", "Run schema migrations"),
    ],
    DeviceType.NETWORK: [
        DeviceCapability("http", "HTTP requests"),
        DeviceCapability("websocket", "WebSocket connections"),
    ],
    DeviceType.STORAGE: [
        DeviceCapability("read", "Read files"),
        DeviceCapability("write", "Write files"),
        DeviceCapability("list", "List directory contents"),
    ],
}


class DeviceManager:
    """Kernel device manager — singleton, thread-safe."""

    def __init__(self):
        self._devices: dict[str, Device] = {}
        self._lock = threading.Lock()
        self._call_timestamps: dict[str, list[float]] = {}
        self._health_thread: threading.Thread | None = None
        self._health_running = False

    def start_health_checks(self, interval: float = DEVICE_HEALTH_INTERVAL) -> None:
        if self._health_running:
            return
        self._health_running = True
        def _loop():
            while self._health_running:
                time.sleep(interval)
                self._check_all_health()
        self._health_thread = threading.Thread(target=_loop, daemon=True)
        self._health_thread.start()

    def stop_health_checks(self) -> None:
        self._health_running = False

    def _check_all_health(self) -> None:
        with self._lock:
            for name in list(self._devices.keys()):
                dev = self._devices.get(name)
                if not dev:
                    continue
                if dev.error_count > dev.call_count * DEVICE_DEGRADED_THRESHOLD and dev.call_count > DEVICE_MIN_CALLS_DEGRADED:
                    dev.health = DeviceHealth.DEGRADED
                if dev.error_count > dev.call_count * DEVICE_DOWN_THRESHOLD and dev.call_count > DEVICE_MIN_CALLS_DOWN:
                    dev.health = DeviceHealth.DOWN

    def register(self, name: str, device_type: DeviceType,
                 rate_limit: int | None = None, rate_window: float = 1.0,
                 description: str = "", capabilities: list[str] | None = None,
                 version: str = "") -> dict:
        with self._lock:
            if name in self._devices:
                return {"success": False, "error": f"device '{name}' already registered"}
            from .settings import get_settings
            s = get_settings()
            rl = rate_limit or s.get(f"device.{name}.rate_limit", s.get("device.rate_limit_default", 10))
            caps = [DeviceCapability(c, c.replace("-", " ").title()) for c in (capabilities or [])]
            if not caps:
                caps = list(_CAPABILITY_REGISTRY.get(device_type, []))
            self._devices[name] = Device(
                name=name, device_type=device_type, rate_limit=rl,
                rate_window=rate_window, description=description,
                capabilities=caps, version=version,
            )
            self._call_timestamps[name] = []
            logger.info("device registered: %s (%s, %d caps)", name, device_type.name, len(caps))
            return {"success": True, "device": name}

    def check_rate(self, name: str) -> dict:
        with self._lock:
            dev = self._devices.get(name)
            if not dev:
                return {"allowed": False, "error": f"unknown device: {name}"}
            now = time.time()
            ts_list = self._call_timestamps.setdefault(name, [])
            cutoff = now - dev.rate_window
            ts_list[:] = [t for t in ts_list if t > cutoff]
            remaining = dev.rate_limit - len(ts_list)
            if remaining <= 0:
                reset_after = ts_list[0] + dev.rate_window - now if ts_list else 0
                return {"allowed": False, "remaining": 0,
                        "reset_after": round(reset_after, 2)}
            return {"allowed": True, "remaining": remaining, "reset_after": 0}

    def get(self, name: str) -> Device | None:
        """Return the Device object for inspection."""
        with self._lock:
            return self._devices.get(name)

    def record_call(self, name: str, success: bool = True) -> None:
        with self._lock:
            dev = self._devices.get(name)
            if not dev:
                return
            dev.last_used = time.time()
            dev.call_count += 1
            if not success:
                dev.error_count += 1
            self._call_timestamps.setdefault(name, []).append(time.time())

    def set_health(self, name: str, health: DeviceHealth) -> bool:
        with self._lock:
            dev = self._devices.get(name)
            if not dev:
                return False
            dev.health = health
            return True

    def list(self, device_type: DeviceType | None = None) -> list[dict]:
        with self._lock:
            return [{
                "name": d.name, "type": d.device_type.name,
                "health": d.health.name,
                "rate_limit": d.rate_limit,
                "calls": d.call_count, "errors": d.error_count,
                "last_used": d.last_used,
                "description": d.description,
            } for d in self._devices.values()
               if device_type is None or d.device_type == device_type]

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_devices": len(self._devices),
                "by_type": {t.name: sum(1 for d in self._devices.values()
                                         if d.device_type == t)
                            for t in DeviceType},
                "healthy": sum(1 for d in self._devices.values()
                                if d.health == DeviceHealth.HEALTHY),
                "down": sum(1 for d in self._devices.values()
                             if d.health == DeviceHealth.DOWN),
            }

    def unregister(self, name: str) -> bool:
        with self._lock:
            if name not in self._devices:
                return False
            del self._devices[name]
            self._call_timestamps.pop(name, None)
            return True


_manager: DeviceManager | None = None
_manager_lock = threading.Lock()


def get_device_manager() -> DeviceManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = DeviceManager()
    return _manager


def reset_device_manager() -> None:
    global _manager
    _manager = None
