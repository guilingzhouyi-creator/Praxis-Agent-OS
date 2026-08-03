"""MonitorBusPort adapter — wraps services.monitor_bus behind the port interface.

Eliminates the ``from l3.bus.monitor_bus import MonitorEvent, get_bus``
pattern in kernel layer.
"""

from __future__ import annotations

import logging

from l1.kernel.ports import MonitorBusPort

logger = logging.getLogger(__name__)


class MonitorBusAdapter(MonitorBusPort):
    """Delegates MonitorBusPort calls to ``services.monitor_bus``.

    This bridges the observability event system so kernel code
    emits monitor events through a Port interface.
    """

    def emit(self, type_: str, source: str, severity: str,
             message: str, data: dict | None = None) -> None:
        try:
            from l3.bus.monitor_bus import MonitorEvent, get_bus
            bus = get_bus()
            bus.emit(MonitorEvent(
                type=type_, source=source,
                severity=severity, message=message,
                data=data or {},
            ))
        except Exception as e:
            logger.debug("monitor_bus: emit skipped: %s", e)

    def query(self, type_prefix: str = "", severity: str = "",
              source: str = "", since: float = 0.0,
              limit: int = 100) -> list[dict]:
        try:
            from l3.bus.monitor_bus import get_bus
            return get_bus().query(
                type_prefix=type_prefix, severity=severity,
                source=source, since=since, limit=limit,
            )
        except Exception as e:
            logger.debug("monitor_bus: query skipped: %s", e)
            return []
