"""Settings adapter — bridges kernel.settings API to SettingsCenter.

Moved from kernel/settings.py to resolve architecture violation
(kernel/ must not import services/).

Maintains backward compatibility: all ``from l1.kernel.settings import get_settings``
callers continue to work unchanged.
"""

from __future__ import annotations

from typing import Any

from l3.config.settings_center import get_center


class Settings:
    """Settings — thin wrapper around SettingsCenter.

    All reads/writes delegate to services.settings_center.SettingsCenter,
    which provides three-layer aggregation (L1 defaults / L2 YAML / L3 runtime).
    """

    def __init__(self):
        self._center = get_center()
        # Merge legacy kernel.settings.DEFAULTS into SettingsCenter L2
        # (deployment-config layer, not persisted) so that keys like
        # llm.provider, kernel.allocator.* remain accessible without
        # polluting the L3 runtime-override file.
        from l1.kernel.settings import DEFAULTS as _legacy
        for _k, _v in _legacy.items():
            if self._center.get(_k) is None:
                self._center.set_l2(_k, _v)

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for a key, or the given default if absent."""
        return self._center.get(key, default)

    def set_l2(self, key: str, value: Any) -> dict:
        """Write into the L2 (praxis.yaml) layer — not persisted."""
        return self._center.set_l2(key, value)

    def set(self, key: str, value: Any) -> dict:
        """Write a runtime setting and return the result dict."""
        return self._center.set(key, value)

    def set_many(self, pairs: dict[str, Any]) -> dict:
        """Write multiple runtime settings and return the result dict."""
        return self._center.set_many(pairs)

    def all(self) -> dict[str, Any]:
        """Return all aggregated settings as a flat key-value dict."""
        return self._center.all()

    def category(self, prefix: str) -> dict[str, Any]:
        """Return all settings whose keys start with the given prefix."""
        return {k: v for k, v in self._center.all().items() if k.startswith(prefix)}

    def reset(self, key: str) -> dict:
        """Reset a runtime setting to its defaults and return the result dict."""
        return self._center.reset(key)

    def reset_all(self) -> dict:
        """Reset all runtime settings to their defaults and return the result dict."""
        return self._center.reset_all()


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the Settings singleton, creating it on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset the Settings singleton so the next access re-creates it."""
    global _settings
    _settings = None
