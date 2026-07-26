"""Adapters — concrete implementations of kernel.ports interfaces.

命名规范 (Naming convention):
  File:                  Class:
  i18n_yaml.py           YamlI18nAdapter
  channel_ring.py         RingChannel
  worker_thread.py        ThreadPoolWorker
  bus_memory.py           MemoryBusAdapter
  card_registry.py        CardRegistryAdapter
  monitor_bus.py          MonitorBusAdapter

导入规范 (Import convention):
  # In wiring.py (集中注册点):
  from services.adapters import YamlI18nAdapter, RingChannel, ThreadPoolWorker

  # Outside wiring.py — use get_port("name") instead of direct adapter import:
  from kernel.ports import get_port
  i18n = get_port("i18n")

Adapter contract:
  - Every adapter class implements exactly one kernel.ports.*Port interface.
  - Constructor accepts only configuration primitives (str, int, float, bool, dict).
    Port references are injected at wiring time, never at construction.
  - Thread-safe unless documented otherwise.
"""

from services.adapters.i18n_yaml import YamlI18nAdapter
from services.adapters.channel_ring import RingChannel
from services.adapters.worker_thread import ThreadPoolWorker
from services.adapters.bus_memory import MemoryBusAdapter
from services.adapters.card_registry import CardRegistryAdapter
from services.adapters.monitor_bus import MonitorBusAdapter

__all__ = [
    "YamlI18nAdapter",
    "RingChannel",
    "ThreadPoolWorker",
    "MemoryBusAdapter",
    "CardRegistryAdapter",
    "MonitorBusAdapter",
]
