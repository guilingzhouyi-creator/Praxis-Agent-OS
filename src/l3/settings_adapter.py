"""Settings adapter — bridges kernel.settings API to SettingsCenter.

Moved from kernel/settings.py to resolve architecture violation
(kernel/ must not import services/).

Maintains backward compatibility: all ``from l1.kernel.settings import get_settings``
callers continue to work unchanged.
"""

from __future__ import annotations

from typing import Any

from .settings_center import SettingsCenter, get_center


class Settings:
    """Settings — thin wrapper around SettingsCenter.

    All reads/writes delegate to services.settings_center.SettingsCenter,
    which provides three-layer aggregation (L1 defaults / L2 YAML / L3 runtime).
    """

    def __init__(self):
        self._center = get_center()
        # Merge legacy kernel.settings.DEFAULTS into SettingsCenter L3
        # so that keys like llm.provider, kernel.allocator.* remain accessible.
        from l1.kernel.settings import DEFAULTS as _legacy
        for _k, _v in _legacy.items():
            if self._center.get(_k) is None:
                self._center.set(_k, _v)

    def get(self, key: str, default: Any = None) -> Any:
        return self._center.get(key, default)

    def set(self, key: str, value: Any) -> dict:
        return self._center.set(key, value)

    def set_many(self, pairs: dict[str, Any]) -> dict:
        return self._center.set_many(pairs)

    def all(self) -> dict[str, Any]:
        return self._center.all()

    def category(self, prefix: str) -> dict[str, Any]:
        return {k: v for k, v in self._center.all().items() if k.startswith(prefix)}

    def reset(self, key: str) -> dict:
        return self._center.reset(key)

    def reset_all(self) -> dict:
        return self._center.reset_all()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
