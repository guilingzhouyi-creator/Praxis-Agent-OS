"""Config service — hierarchical config with file/env/CLI sources.

Layer:   Defaults → Config file → Environment → CLI args → Runtime
Merge:   Deep merge, later sources override earlier ones
Live:    Watch config file for changes, auto-reload
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from l1.kernel.params.agent import LOOP_MAX_ATTEMPTS
from l1.kernel.params.api import API_GATEWAY_HOST, API_GATEWAY_PORT
from l1.kernel.params.system import (
    CI_DEFAULT_TIMEOUT,
    FAULT_CHECK_INTERVAL,
    RING1_CAPACITY,
    RING2_CAPACITY,
    RING3_CAPACITY,
)
from l1.kernel.params.tool import TOOL_SEARCH_TIMEOUT
from l3._base import BaseService

logger = logging.getLogger(__name__)


class ConfigService(BaseService):
    """Hierarchical configuration service."""

    def __init__(self):
        super().__init__("config")
        self._data: dict[str, Any] = {}
        self._files: list[Path] = []
        self._lock = threading.RLock()
        self._watch_thread: threading.Thread | None = None
        self._running = False

    def _on_start(self) -> dict:
        self._load_defaults()
        return {"success": True}

    def _on_stop(self) -> dict:
        self._running = False
        return {"success": True}

    def _load_defaults(self) -> None:
        self._data = {
            "praxis": {"port": API_GATEWAY_PORT, "host": API_GATEWAY_HOST, "debug": False},
            "agent": {"timeout": CI_DEFAULT_TIMEOUT, "max_retries": LOOP_MAX_ATTEMPTS, "heartbeat_interval": FAULT_CHECK_INTERVAL},
            "gate": {"allow_threshold": 3.0, "escalate_threshold": 11.0},
            "memory": {"ring1_capacity": RING1_CAPACITY, "ring2_capacity": RING2_CAPACITY, "ring3_capacity": RING3_CAPACITY},
            "network": {"timeout": TOOL_SEARCH_TIMEOUT, "user_agent": "Praxis/1.0"},
        }

    def load_file(self, path: str) -> dict:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "error": "file not found"}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self._deep_merge(self._data, data)
            self._files.append(p)
            logger.info("config loaded: %s", p)
            return {"success": True, "source": str(p)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        with self._lock:
            val = self._data
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k)
                else:
                    return default
            return val if val is not None else default

    def set(self, key: str, value: Any) -> dict:
        keys = key.split(".")
        with self._lock:
            target = self._data
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            target[keys[-1]] = value
        return {"success": True, "key": key, "value": value}

    def all(self) -> dict:
        with self._lock:
            return dict(self._data)

    def _deep_merge(self, base: dict, override: dict) -> None:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v


_service: ConfigService | None = None


def get_service() -> ConfigService:
    global _service
    if _service is None:
        _service = ConfigService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None
