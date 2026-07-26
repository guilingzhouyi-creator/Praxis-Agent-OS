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
  from l4.adapters import YamlI18nAdapter, RingChannel, ThreadPoolWorker

  # Outside wiring.py — use get_port("name") instead of direct adapter import:
  from l1.kernel.ports import get_port
  i18n = get_port("i18n")

Adapter contract:
  - Every adapter class implements exactly one kernel.ports.*Port interface.
  - Constructor accepts only configuration primitives (str, int, float, bool, dict).
    Port references are injected at wiring time, never at construction.
  - Thread-safe unless documented otherwise.
"""

from l4.adapters.i18n_yaml import YamlI18nAdapter
from l4.adapters.channel_ring import RingChannel
from l4.adapters.worker_thread import ThreadPoolWorker
from l4.adapters.bus_memory import MemoryBusAdapter
from l4.adapters.card_registry import CardRegistryAdapter
from l4.adapters.monitor_bus import MonitorBusAdapter

__all__ = [
    "YamlI18nAdapter",
    "RingChannel",
    "ThreadPoolWorker",
    "MemoryBusAdapter",
    "CardRegistryAdapter",
    "MonitorBusAdapter",
]
