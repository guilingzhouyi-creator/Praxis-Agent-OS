"""Wiring — centralized port-to-adapter assembly at boot.

Single source of truth for which adapter implements which port.
All registrations happen here, not scattered across modules.

Usage:
  from services.wiring import wire_defaults, wire_from_config

  # Default wiring (all stdlib adapters)
  wire_defaults()

  # Config-driven wiring (from praxis.yaml or env)
  wire_from_config({
      "transport": "tcp",
      "i18n": {"adapter": "yaml", "locale_dir": "./locales"},
      "worker": {"min": 4, "max": 16},
  })
"""

from __future__ import annotations

import logging
from typing import Any

from kernel.ports import (
    register_port, get_port, reset_ports,
    TransportPort, ChannelPort, EventBusPort,
    WorkerPort, I18nPort, CardRegistryPort, MonitorBusPort,
)
from kernel.params import (
    I18N_DEFAULT_LOCALE, I18N_LOCALE_DIR,
    CHANNEL_RING_CAPACITY, CHANNEL_RING_OVERWRITE,
    WORKER_POOL_MIN, WORKER_POOL_MAX, WORKER_POOL_QUEUE_SIZE,
)

logger = logging.getLogger(__name__)


# ── Default wiring ───────────────────────────────────────────────────────────


def wire_defaults() -> dict[str, str]:
    """Register all default adapters.

    Uses stdlib-only implementations everywhere (no external dependencies).
    Returns a dict of {port_name: adapter_name}.
    """
    registry: dict[str, str] = {}

    # I18nPort — YAML file adapter
    from services.adapters.i18n_yaml import YamlI18nAdapter
    i18n = YamlI18nAdapter(locale_dir=I18N_LOCALE_DIR,
                           default_locale=I18N_DEFAULT_LOCALE)
    register_port("i18n", i18n)
    registry["i18n"] = "yaml"

    # WorkerPort — thread pool
    from services.adapters.worker_thread import ThreadPoolWorker
    worker = ThreadPoolWorker(
        min_workers=WORKER_POOL_MIN,
        max_workers=WORKER_POOL_MAX,
        queue_size=WORKER_POOL_QUEUE_SIZE,
    )
    register_port("worker", worker)
    registry["worker"] = "thread"

    # ChannelPort — ring buffer
    from services.adapters.channel_ring import RingChannel
    channel = RingChannel(capacity=CHANNEL_RING_CAPACITY,
                          overwrite=CHANNEL_RING_OVERWRITE)
    register_port("channel", channel)
    registry["channel"] = "ring"

    # EventBusPort — in-memory pub/sub
    from services.adapters.bus_memory import MemoryBusAdapter
    register_port("event_bus", MemoryBusAdapter())
    registry["event_bus"] = "memory"

    # TransportPort — default is NOT set here;
    # NetKernel creates TcpTransport internally by default for backward compat.
    # Call wire_transport() explicitly to override with TcpAdapter.

    # CardRegistryPort — delegated adapter (wraps services.card_unified)
    from services.adapters.card_registry import CardRegistryAdapter
    register_port("card_registry", CardRegistryAdapter())
    registry["card_registry"] = "card_unified"

    # MonitorBusPort — delegated adapter (wraps services.monitor_bus)
    from services.adapters.monitor_bus import MonitorBusAdapter
    register_port("monitor_bus", MonitorBusAdapter())
    registry["monitor_bus"] = "monitor_bus"

    logger.info("wiring: default adapters registered: %s", registry)
    return registry


def wire_transport(adapter_name: str = "tcp", **kwargs: Any) -> str:
    """Register a TransportPort adapter by name.

    Args:
        adapter_name: "tcp" (default, uses TcpAdapter with WorkerPort + ChannelPort)
        **kwargs: passed to the adapter constructor

    Returns the adapter name for confirmation.
    """
    worker = get_port("worker") if _is_registered("worker") else None
    channel = get_port("channel") if _is_registered("channel") else None

    if adapter_name == "tcp":
        from kernel.net_transport import TcpAdapter
        adapter = TcpAdapter(worker_pool=worker, msg_channel=channel, **kwargs)
    else:
        raise ValueError(f"unknown transport adapter: {adapter_name}")

    register_port("transport", adapter)
    logger.info("wiring: transport=%s registered", adapter_name)
    return adapter_name


def wire_from_config(cfg: dict) -> dict[str, str]:
    """Wire adapters from a configuration dict.

    The *cfg* dict is typically loaded from ``praxis.yaml`` section
    ``ports:`` or environment variables.

    Example:
        wire_from_config({
            "transport": {"adapter": "tcp"},
            "i18n": {"adapter": "yaml", "locale_dir": "/etc/praxis/locales"},
            "worker": {"adapter": "thread", "min_workers": 8},
        })
    """
    registry: dict[str, str] = {}

    # I18n
    i18n_cfg = cfg.get("i18n", {})
    if i18n_cfg.get("adapter", "yaml") == "yaml":
        from services.adapters.i18n_yaml import YamlI18nAdapter
        i18n = YamlI18nAdapter(
            locale_dir=i18n_cfg.get("locale_dir", I18N_LOCALE_DIR),
            default_locale=i18n_cfg.get("default_locale", I18N_DEFAULT_LOCALE),
        )
        register_port("i18n", i18n)
        registry["i18n"] = "yaml"

    # Worker
    worker_cfg = cfg.get("worker", {})
    if worker_cfg.get("adapter", "thread") == "thread":
        from services.adapters.worker_thread import ThreadPoolWorker
        worker = ThreadPoolWorker(
            min_workers=worker_cfg.get("min", WORKER_POOL_MIN),
            max_workers=worker_cfg.get("max", WORKER_POOL_MAX),
            queue_size=worker_cfg.get("queue_size", WORKER_POOL_QUEUE_SIZE),
        )
        register_port("worker", worker)
        registry["worker"] = "thread"

    # Channel
    chan_cfg = cfg.get("channel", {})
    if chan_cfg.get("adapter", "ring") == "ring":
        from services.adapters.channel_ring import RingChannel
        channel = RingChannel(
            capacity=chan_cfg.get("capacity", CHANNEL_RING_CAPACITY),
            overwrite=chan_cfg.get("overwrite", CHANNEL_RING_OVERWRITE),
        )
        register_port("channel", channel)
        registry["channel"] = "ring"

    # EventBus
    if "event_bus" not in registry:
        from services.adapters.bus_memory import MemoryBusAdapter
        register_port("event_bus", MemoryBusAdapter())
        registry["event_bus"] = "memory"

    # Transport
    transport_cfg = cfg.get("transport", {})
    if transport_cfg.get("adapter"):
        wire_transport(**transport_cfg)

    # CardRegistry + MonitorBus (always defaults)
    if not _is_registered("card_registry"):
        from services.adapters.card_registry import CardRegistryAdapter
        register_port("card_registry", CardRegistryAdapter())
        registry["card_registry"] = "card_unified"

    if not _is_registered("monitor_bus"):
        from services.adapters.monitor_bus import MonitorBusAdapter
        register_port("monitor_bus", MonitorBusAdapter())
        registry["monitor_bus"] = "monitor_bus"

    logger.info("wiring: config-driven adapters: %s", registry)
    return registry


def _is_registered(name: str) -> bool:
    try:
        get_port(name)
        return True
    except KeyError:
        return False


def reset_all() -> None:
    """Reset all ports for testing or hot-reload."""
    reset_ports()
    logger.info("wiring: all ports reset")
