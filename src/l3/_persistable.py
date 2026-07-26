"""PersistableMixin — atomic JSON persistence for in-memory services.

Every service that subclasses this gets:
  - _persist_path: path to JSON file (configurable via params)
  - _persist()    — atomic write (tmp + replace)
  - _restore()    — read + version check + migrate
  - _auto_save()  — periodic background save via daemon thread

Usage:
  class MyService(PersistableMixin):
      persistence_kind = "card_registry"
      def _serialize(self) -> dict: ...
      def _deserialize(self, data: dict) -> bool: ...
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from l1.kernel.versioning import check_and_migrate, stamp

logger = logging.getLogger(__name__)


class PersistableMixin(ABC):
    persistence_kind: str = ""
    _persist_path: str = ""
    _auto_save_interval: float = 30.0
    _lock: threading.RLock | None = None
    _auto_save_stop: threading.Event | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def _init_persistence(self, persist_path: str, auto_save_interval: float = 30.0) -> None:
        self._persist_path = persist_path
        self._auto_save_interval = auto_save_interval

    @abstractmethod
    def _serialize(self) -> dict:
        ...

    @abstractmethod
    def _deserialize(self, data: dict) -> bool:
        ...

    def save(self) -> dict:
        """Public: save current state to disk."""
        return self._persist()

    def load(self) -> dict:
        """Public: reload state from disk."""
        return self._restore()

    def _persist(self) -> dict:
        data = self._serialize()
        data = stamp(data, self.persistence_kind)
        try:
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, self._persist_path)
            return {"success": True, "path": self._persist_path}
        except Exception as e:
            logger.warning("persist %s: %s", self.persistence_kind, e)
            return {"success": False, "error": str(e)}

    def _restore(self) -> dict:
        if not os.path.exists(self._persist_path):
            return {"success": False, "error": "no file"}
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {"success": False, "error": f"read failed: {e}"}
        try:
            data = check_and_migrate(data, self.persistence_kind)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        try:
            ok = self._deserialize(data)
        except Exception as e:
            return {"success": False, "error": f"deserialize failed: {e}"}
        return {"success": ok, "entries": len(data)}

    def _start_auto_save(self) -> None:
        self._auto_save_stop = threading.Event()
        def _loop():
            while not self._auto_save_stop.is_set():
                if self._auto_save_stop.wait(self._auto_save_interval):
                    break
                self._persist()
        t = threading.Thread(target=_loop, daemon=True, name=f"autosave-{self.persistence_kind}")
        t.start()

    def _stop_auto_save(self) -> None:
        if self._auto_save_stop:
            self._auto_save_stop.set()
